"""Real-data precision + would-flag analysis for classifier Rule 15
(basket_enumeration). Read-only — flags NOTHING, writes NOTHING.

Scope: prediction_category='ticker_call' with a non-empty
source_verbatim_quote (the only category Rule 15 applies to). Reports the
total would-flag count (the backfill estimate), the YouTube vs non-YouTube
split, confirms the BWB/AA tariff row flags, and prints a sample of
would-flags for hand-labelled precision judgement.

Usage: DATABASE_PUBLIC_URL=... python3 backend/scripts/realdata_rule_15_precision.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "jobs"))

from sqlalchemy import create_engine, text  # noqa: E402
import classifier_validation as gate  # noqa: E402

DBURL = (os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL"))
if not DBURL:
    print("No DB URL", file=sys.stderr)
    sys.exit(2)

eng = create_engine(DBURL)
SAMPLE_CAP = int(os.environ.get("SAMPLE_CAP", "45"))

with eng.connect().execution_options(stream_results=True) as db:
    total = yt = nyt = flagged = flagged_yt = flagged_scored = 0
    samples = []
    bwb_hit = None
    res = db.execute(text(
        "SELECT p.id, p.ticker, p.outcome, p.transcript_video_id, p.source_type, "
        "       f.name AS fc, p.source_verbatim_quote AS q "
        "FROM predictions p LEFT JOIN forecasters f ON f.id = p.forecaster_id "
        "WHERE p.prediction_category='ticker_call' "
        "  AND p.source_verbatim_quote IS NOT NULL "
        "  AND length(trim(p.source_verbatim_quote)) > 0"
    ))
    for r in res:
        total += 1
        is_yt = r.transcript_video_id is not None
        yt += is_yt
        nyt += (not is_yt)
        ok, _ = gate.check_basket_enumeration(r.q, r.ticker, db)
        if ok:
            continue
        flagged += 1
        flagged_yt += is_yt
        if r.outcome in ("hit", "near", "miss", "correct", "incorrect"):
            flagged_scored += 1
        if r.id == 616182:
            bwb_hit = True
        if len(samples) < SAMPLE_CAP:
            samples.append((r.id, r.ticker, r.outcome, r.fc, (r.q or "")[:240]))

    print("=" * 78)
    print(f"Rule 15 (basket_enumeration) — would-flag over ticker_call w/ quote")
    print("=" * 78)
    print(f"ticker_call rows scanned : {total:,}  (YouTube {yt:,} / non-YT {nyt:,})")
    print(f"WOULD-FLAG total         : {flagged:,}  "
          f"({flagged/total*100:.3f}%)   YouTube {flagged_yt:,} / non-YT {flagged-flagged_yt:,}")
    print(f"  of which already SCORED: {flagged_scored:,}  (these drop from leaderboard if backfilled)")
    print(f"BWB/AA tariff row (id 616182) flagged: {bwb_hit!r}")
    print("\n" + "-" * 78)
    print(f"Sample of up to {SAMPLE_CAP} would-flags (hand-label P=basket / FP=real call):")
    print("-" * 78)
    for pid, tk, oc, fc, q in samples:
        print(f"\n[id {pid} | {tk} | {oc} | {fc}]")
        print(f"  {q}")
