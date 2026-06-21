"""Population requote pass — APPLY (2026-06-21). EVIDENCE ONLY.

Reads the per-row verdicts and applies ONLY the REQUOTE action:
  source_verbatim_quote  <- the byte-exact transcript sentence carrying the call
  source_timestamp_seconds <- the segment containing that sentence
  source_timestamp_method  <- 'requote_pop_2026_06_21'   (varchar(32) safe, 22 chars)
  evaluation_summary       <- prepend marker + [pre_remediation] JSON of the ORIGINAL
                              quote/ts/method (reversible) + the prior summary.

HARD INVARIANT — this script NEVER changes outcome, direction, actual_return, or
evaluation_date (the four scoring fields). It snapshots those + the quote/ts for
EVERY cohort row before the write and re-reads them after, asserting zero drift on
the scoring fields and that ONLY requoted rows changed quote/ts.

KEEP / INSUFFICIENT -> no write. DIRECTION_MISMATCH + NO_CALL -> written to
requote_pop_review_direction_mismatch_2026_06_21.json for HUMAN adjudication
(NO auto-flip — a direction flip is a scoring change, human-only).

flag-not-delete, idempotent (NOT LIKE marker guard), transactional. No stats
refresh needed (no outcomes changed).

Run:  DATABASE_PUBLIC_URL=... python3 backend/scripts/requote_pop_apply_2026_06_21.py
"""
import json
import os
import sys

import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
COHORT = os.path.join(HERE, "requote_pop_cohort_2026_06_21.json")
VERDICTS = os.path.join(HERE, "requote_pop_verdicts_2026_06_21.json")
REVIEW = os.path.join(HERE, "requote_pop_review_direction_mismatch_2026_06_21.json")
RESULTS = os.path.join(HERE, "requote_pop_apply_results_2026_06_21.json")
MARKER = "requote_pop_2026_06_21"
METHOD = "requote_pop_2026_06_21"

SCORING_COLS = ["outcome", "direction", "actual_return", "evaluation_date"]


def snapshot(cur, ids):
    cur.execute(
        f"SELECT id, {', '.join(SCORING_COLS)}, source_verbatim_quote, "
        f"source_timestamp_seconds FROM predictions WHERE id = ANY(%s)", (ids,))
    out = {}
    for row in cur.fetchall():
        pid = row[0]
        d = {c: row[1 + i] for i, c in enumerate(SCORING_COLS)}
        d["source_verbatim_quote"] = row[1 + len(SCORING_COLS)]
        d["source_timestamp_seconds"] = row[2 + len(SCORING_COLS)]
        out[pid] = d
    return out


def main():
    cohort = {str(r["id"]): r for r in json.load(open(COHORT))["rows"]}
    verdicts = json.load(open(VERDICTS))
    ids = [int(p) for p in cohort]

    conn = psycopg2.connect(os.environ["DATABASE_PUBLIC_URL"])
    cur = conn.cursor()

    before = snapshot(cur, ids)

    # Normalize: a DIRECTION_MISMATCH whose grounded direction actually MATCHES the
    # labeled direction is NOT a mismatch (the call is already correct / the judge
    # mislabeled) -> treat as KEEP. Only a genuinely OPPOSITE (or unknown-direction)
    # row belongs in the human-adjudication review. Documented in results.
    normalized = []
    for p, v in verdicts.items():
        if v["verdict"] == "DIRECTION_MISMATCH":
            gd = (v.get("grounded_direction") or "").lower()
            lab = (cohort.get(p, {}).get("direction") or "").lower()
            if gd and gd == lab:
                v["verdict"] = "KEEP"
                v["why"] = "(normalized: grounded==label, not a mismatch) " + (v.get("why") or "")
                normalized.append(int(p))
    if normalized:
        print(f"normalized DIRECTION_MISMATCH->KEEP (grounded==label): {normalized}")

    # Buckets
    requote = {p: v for p, v in verdicts.items()
               if v["verdict"] == "REQUOTE" and v.get("quote") and v.get("ts") is not None}
    mismatch = {p: v for p, v in verdicts.items() if v["verdict"] == "DIRECTION_MISMATCH"}
    nocall = {p: v for p, v in verdicts.items() if v["verdict"] == "NO_CALL"}
    keep = [p for p, v in verdicts.items() if v["verdict"] == "KEEP"]
    insufficient = [p for p, v in verdicts.items() if v["verdict"] == "INSUFFICIENT"]
    print(f"verdicts: REQUOTE={len(requote)} KEEP={len(keep)} "
          f"DIRECTION_MISMATCH={len(mismatch)} NO_CALL={len(nocall)} "
          f"INSUFFICIENT={len(insufficient)} (total judged {len(verdicts)})")

    # ---- apply REQUOTE (evidence-only) ----
    applied = skipped_noop = 0
    for p, v in requote.items():
        pid = int(p)
        new_q = v["quote"]
        new_ts = int(v["ts"])
        cur_q = before.get(pid, {}).get("source_verbatim_quote")
        cur_ts = before.get(pid, {}).get("source_timestamp_seconds")
        if (new_q or "") == (cur_q or "") and new_ts == cur_ts:
            skipped_noop += 1
            continue
        cur.execute(
            """
            UPDATE predictions SET
              source_verbatim_quote = %s,
              source_timestamp_seconds = %s,
              source_timestamp_method = %s,
              evaluation_summary =
                '[' || %s || ' evidence-only: verbatim quote + timestamp replaced; '
                || 'outcome/direction/return UNCHANGED] [pre_remediation] '
                || json_build_object(
                     'source_verbatim_quote', source_verbatim_quote,
                     'source_timestamp_seconds', source_timestamp_seconds,
                     'source_timestamp_method', source_timestamp_method)::text
                || ' | prior: ' || COALESCE(evaluation_summary, '(none)')
            WHERE id = %s
              AND COALESCE(evaluation_summary, '') NOT LIKE '%%' || %s || '%%'
            """,
            (new_q, new_ts, METHOD, MARKER, pid, MARKER))
        applied += cur.rowcount
    conn.commit()
    print(f"REQUOTE applied: {applied} (no-op identical skipped: {skipped_noop})")

    # ---- invariant verification ----
    after = snapshot(cur, ids)
    violations = []
    changed_quote_ids = set()
    for pid in ids:
        b, a = before.get(pid, {}), after.get(pid, {})
        for c in SCORING_COLS:
            if b.get(c) != a.get(c):
                violations.append({"id": pid, "field": c, "before": str(b.get(c)),
                                   "after": str(a.get(c))})
        if (b.get("source_verbatim_quote") != a.get("source_verbatim_quote")
                or b.get("source_timestamp_seconds") != a.get("source_timestamp_seconds")):
            changed_quote_ids.add(pid)
    # Every quote/ts change MUST be an intended REQUOTE id
    intended = {int(p) for p in requote}
    unexpected = changed_quote_ids - intended
    print(f"INVARIANT scoring-field violations: {len(violations)}")
    print(f"rows whose quote/ts changed: {len(changed_quote_ids)} "
          f"(unexpected, not in REQUOTE set: {len(unexpected)})")
    if violations:
        print("  !!! SCORING DRIFT:", violations[:10])
    if unexpected:
        print("  !!! UNEXPECTED quote/ts change ids:", sorted(unexpected)[:20])

    # marker count
    cur.execute("SELECT count(*) FROM predictions WHERE evaluation_summary LIKE %s",
                (f"%{MARKER}%",))
    marker_total = cur.fetchone()[0]
    print(f"total rows carrying '{MARKER}' marker: {marker_total}")

    # ---- review JSON (human adjudication; NO mutation) ----
    review = {
        "generated": "2026-06-21",
        "note": "Population requote pass — rows whose transcript window contradicts the "
                "stored label (DIRECTION_MISMATCH) or shows no committed call (NO_CALL). "
                "NO mutation applied. A direction flip / re-score is a SCORING change and "
                "is human-only. Adjudicate, then run an id-pinned scoring fix if warranted.",
        "direction_mismatch": [],
        "no_call": [],
    }
    for p, v in mismatch.items():
        r = cohort.get(p, {})
        review["direction_mismatch"].append({
            "id": int(p), "ticker": r.get("ticker"), "labeled_direction": r.get("direction"),
            "grounded_direction": v.get("grounded_direction"),
            "displayed_quote": r.get("vq"), "window_quote": v.get("quote"),
            "why": v.get("why"), "outcome": before.get(int(p), {}).get("outcome"),
            "actual_return": str(before.get(int(p), {}).get("actual_return")),
            "vid": r.get("vid"), "flag": r.get("flag"),
            "generating_model": r.get("generating_model") or r.get("verified_by")})
    for p, v in nocall.items():
        r = cohort.get(p, {})
        review["no_call"].append({
            "id": int(p), "ticker": r.get("ticker"), "labeled_direction": r.get("direction"),
            "displayed_quote": r.get("vq"), "why": v.get("why"),
            "outcome": before.get(int(p), {}).get("outcome"),
            "actual_return": str(before.get(int(p), {}).get("actual_return")),
            "vid": r.get("vid"), "flag": r.get("flag"),
            "generating_model": r.get("generating_model") or r.get("verified_by")})
    json.dump(review, open(REVIEW, "w"), indent=2)
    print(f"review JSON: {len(review['direction_mismatch'])} direction_mismatch + "
          f"{len(review['no_call'])} no_call -> {os.path.basename(REVIEW)}")

    # ---- results ledger ----
    json.dump({
        "generated": "2026-06-21", "cohort_size": len(cohort),
        "judged": len(verdicts),
        "counts": {"REQUOTE": len(requote), "KEEP": len(keep),
                   "DIRECTION_MISMATCH": len(mismatch), "NO_CALL": len(nocall),
                   "INSUFFICIENT": len(insufficient)},
        "requote_applied": applied, "requote_noop_skipped": skipped_noop,
        "normalized_mismatch_to_keep": normalized,
        "marker_total": marker_total,
        "invariant_violations": violations,
        "unexpected_quote_changes": sorted(unexpected),
    }, open(RESULTS, "w"), indent=0)
    conn.close()

    ok = (not violations) and (not unexpected)
    print("\n" + ("OK — 0 invariant violations, all changes intended."
                  if ok else "FAILED — see violations above."))
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
