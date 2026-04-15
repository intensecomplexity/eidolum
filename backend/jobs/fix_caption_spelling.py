"""
Fix auto-caption spelling errors in training-data quotes.

YouTube auto-captions frequently mangle company names ("Salana" for Solana,
"Invidia" for Nvidia, "Palanteer" / "palunteer" for Palantir, "fizer" for
Pfizer, ...). Those misspellings end up in source_verbatim_quote and would
teach the fine-tuned model the wrong spelling.

This is a pure string-fix pass — no Haiku calls, no API cost. Each rule is a
whole-word POSIX regex (\\y...\\y) so we never clobber a correctly spelled
substring (e.g. "fizer" must not match inside "Pfizer").

Also sweeps a small set of garbled caption artifacts — quotes where the
caption parser jammed a percentage into an adjacent number ("33.577002") —
and flags those rows as excluded_from_training instead of trying to repair
them.

Usage (from backend/):
    python -m jobs.fix_caption_spelling             # dry run
    python -m jobs.fix_caption_spelling --apply     # write to DB

Scope guard:
    verified_by = 'youtube_haiku_v1'
    AND excluded_from_training = FALSE
"""
import argparse
import os
import sys


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text as sql_text
from database import BgSessionLocal


TAG = "[spelling]"

# (wrong, right) — wrong is matched whole-word, case-insensitive.
# Replacement is literal; matches always collapse to the canonical form.
CORRECTIONS: list[tuple[str, str]] = [
    ("Salana",    "Solana"),
    ("Invidia",   "Nvidia"),
    ("Palanteer", "Palantir"),
    ("Palenteer", "Palantir"),
    ("palunteer", "Palantir"),
    ("Pallantir", "Palantir"),
    ("kryptos",   "crypto"),
    ("Etherium",  "Ethereum"),
    ("Bitcoint",  "Bitcoin"),
    ("fizer",     "Pfizer"),
    ("Chewie",    "Chewy"),
]

_GARBLED_EXCLUSION_REASON = "garbled_caption_artifact"
_GARBLED_EXCLUSION_VERSION = "v16.3"

# Quotes where an auto-caption parser ran a percentage into an adjacent
# number — e.g. "33.577002" should be "33.5%. 77,002". Too risky to repair
# automatically, so we flag instead.
_GARBLED_PATTERN = r'[0-9]{2}\.[0-9]{6}'


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fix auto-caption spelling errors in training-data quotes.",
    )
    parser.add_argument("--apply", action="store_true",
                        help="Actually write to DB. Default is dry-run.")
    args = parser.parse_args(argv)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"{TAG} Starting caption-spelling fix ({mode})", flush=True)

    db = BgSessionLocal()
    try:
        return _run(db, apply=args.apply)
    finally:
        db.close()


def _run(db, *, apply: bool) -> int:
    try:
        db.execute(sql_text("SET statement_timeout = 0"))
        db.commit()
    except Exception as _e:
        print(f"{TAG} WARNING: could not disable statement_timeout: {_e}", flush=True)

    spelling_total = 0
    per_rule_counts: list[tuple[str, str, int]] = []

    for wrong, right in CORRECTIONS:
        pattern = rf'\y{wrong}\y'
        n = db.execute(sql_text("""
            SELECT COUNT(*) FROM predictions
            WHERE verified_by = 'youtube_haiku_v1'
              AND excluded_from_training = FALSE
              AND source_verbatim_quote ~* :pattern
        """), {"pattern": pattern}).scalar() or 0
        per_rule_counts.append((wrong, right, n))
        spelling_total += n
        arrow = "→" if n else " "
        print(f"{TAG}   \"{wrong}\" {arrow} \"{right}\": {n} rows", flush=True)

    if apply:
        print(f"\n{TAG} Applying spelling fixes...", flush=True)
        for wrong, right, expected in per_rule_counts:
            if expected == 0:
                continue
            pattern = rf'\y{wrong}\y'
            res = db.execute(sql_text("""
                UPDATE predictions
                   SET source_verbatim_quote = REGEXP_REPLACE(
                       source_verbatim_quote, :pattern, :replacement, 'gi'
                   )
                 WHERE verified_by = 'youtube_haiku_v1'
                   AND excluded_from_training = FALSE
                   AND source_verbatim_quote ~* :pattern
            """), {"pattern": pattern, "replacement": right})
            db.commit()
            print(f"{TAG}   fixed \"{wrong}\" → \"{right}\": {res.rowcount} rows",
                  flush=True)

    # ── Garbled caption artifacts ─────────────────────────────────────────
    print(f"\n{TAG} Garbled-number artifact sweep (pattern {_GARBLED_PATTERN})",
          flush=True)
    garbled_n = db.execute(sql_text("""
        SELECT COUNT(*) FROM predictions
        WHERE verified_by = 'youtube_haiku_v1'
          AND excluded_from_training = FALSE
          AND source_verbatim_quote ~ :pattern
    """), {"pattern": _GARBLED_PATTERN}).scalar() or 0
    print(f"{TAG}   rows to exclude: {garbled_n}", flush=True)

    if apply and garbled_n:
        res = db.execute(sql_text("""
            UPDATE predictions
               SET excluded_from_training = TRUE,
                   exclusion_reason = :reason,
                   exclusion_flagged_at = NOW(),
                   exclusion_rule_version = :ver
             WHERE verified_by = 'youtube_haiku_v1'
               AND excluded_from_training = FALSE
               AND source_verbatim_quote ~ :pattern
        """), {
            "reason": _GARBLED_EXCLUSION_REASON,
            "ver": _GARBLED_EXCLUSION_VERSION,
            "pattern": _GARBLED_PATTERN,
        })
        db.commit()
        print(f"{TAG}   excluded {res.rowcount} rows", flush=True)

    # ── Summary ──────────────────────────────────────────────────────────
    print(f"\n{TAG} ── Summary ──")
    print(f"{TAG}   Spelling corrections (rows touched, pre-apply): {spelling_total}")
    for wrong, right, n in per_rule_counts:
        if n:
            print(f"{TAG}     {wrong:10s} → {right:10s} {n}")
    print(f"{TAG}   Garbled-artifact exclusions:                     {garbled_n}")
    if not apply:
        print(f"\n{TAG} DRY RUN — no DB writes. Pass --apply to commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
