"""Apply Opus-confirmed flips/retickers for the leftover dir/ticker cohort
(fullcov dir/ticker MINUS the adjudicated 297). Reuses the 06-16 flip machinery
(/tmp/flip_apply.py) verbatim in shape, with a distinct marker + snapshot for this
pass and stricter reticker validation (precision-sacred).

Reads Opus verdicts (opus_flip_judge_2026_06_16.py output). Applies ONLY:
  FLIP      -> corrected_direction is bullish|bearish AND differs from the row's
               CURRENT direction. Sets direction, outcome='pending', evaluated_at=NULL.
  RETICKER  -> correct_ticker matches a US symbol pattern, differs from current ticker,
               AND exists in ticker_sectors (the validated universe). Sets ticker,
               entry_price=NULL (re-resolve), outcome='pending', evaluated_at=NULL.
Everything else (KEEP, ambiguous, judge_failed_keep, non-validated reticker) -> NO
mutation; written to the review JSON.

BEFORE state (ticker/direction/outcome/entry/actual_return) snapshotted to
flipx_before_snapshot.json (reversibility — evaluate_batch later overwrites
evaluation_summary, so the snapshot is the audit record; do NOT re-run after re-score).
Idempotent (marker NOT LIKE guard). flag-not-delete. DRY-RUN by default; --commit writes.

Run:
  DATABASE_PUBLIC_URL=... python3 backend/scripts/flipx_apply_2026_06_23.py \
      <verdicts.jsonl> [--commit]
"""
import json, os, re, sys, psycopg2

VP = sys.argv[1] if len(sys.argv) > 1 else "/tmp/flipx_verdicts.jsonl"
COMMIT = "--commit" in sys.argv
MARK = "opus_flip_x_2026_06_23"

# Precision guards found during the spot-check (route to review, never mutate):
# 1) INVERSE / inverse-leveraged ETFs: market-up => ETF-DOWN. Opus conflates the
#    market call with the ETF's direction here (got SH wrong both ways), so its
#    direction verdict is unreliable for these — never auto-flip/reticker them.
INVERSE_ETFS = {"SH", "SDS", "SPXU", "SPXS", "SQQQ", "PSQ", "QID", "DOG", "DXD", "RWM",
    "TWM", "SRTY", "MYY", "MZZ", "FAZ", "SKF", "SRS", "TBT", "TBF", "TTT", "PST", "TMV",
    "TYO", "TYP", "SOXS", "LABD", "DRV", "SCO", "DUG", "ERY", "KOLD", "ZSL", "GLL", "DUST",
    "JDST", "TZA", "SDOW", "EDZ", "EUM", "DRIP", "YANG", "CHAD", "HDGE", "VXX", "UVXY",
    "VIXY", "SVXY", "SARK"}
CASHTAG_RX = re.compile(r"\$[A-Za-z]{1,5}\b")
HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "sonnet_verify_results", "flipx_before_snapshot.json")
APPLIED = os.path.join(HERE, "sonnet_verify_results", "flipx_applied_ids.json")
REVIEW = os.path.join(HERE, "sonnet_verify_results", "flipx_review.json")
SYM = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")

verds = [json.loads(l) for l in open(VP) if l.strip()]
# dedup by id (last real verdict wins)
byid = {}
for v in verds:
    byid[v["id"]] = v
verds = list(byid.values())

conn = psycopg2.connect(os.environ["DATABASE_PUBLIC_URL"])
cur = conn.cursor()
# current state for every judged row (flip against CURRENT direction/ticker, not the
# cohort-time value) + guard against rows already flip-marked by any pass
ids = [v["id"] for v in verds]
cur.execute("""SELECT id, ticker, direction, outcome, COALESCE(evaluation_summary,''),
                 source_type, COALESCE(source_verbatim_quote, exact_quote, '')
               FROM predictions WHERE id = ANY(%s)""", (ids,))
cur_state = {r[0]: {"ticker": r[1], "direction": r[2], "outcome": r[3], "evs": r[4],
                    "src": r[5], "quote": r[6]} for r in cur.fetchall()}
# validated symbol universe (avoid retickering to a hallucinated ticker)
cur.execute("SELECT DISTINCT upper(ticker) FROM ticker_sectors")
UNIVERSE = {r[0] for r in cur.fetchall()}
print(f"ticker_sectors universe: {len(UNIVERSE)} symbols")

flips, rets, review = [], [], []
for v in verds:
    st = cur_state.get(v["id"])
    if st is None:
        review.append({**v, "_skip": "row_gone"}); continue
    if MARK in st["evs"] or "opus_flip_2026_06_16" in st["evs"]:
        review.append({**v, "_skip": "already_flip_marked"}); continue
    vd = v.get("verdict")
    # precision guards (route to review, never mutate)
    if (st["ticker"] or "").upper() in INVERSE_ETFS:
        review.append({**v, "_skip": "inverse_etf_unreliable_direction"}); continue
    if st["src"] == "x" and vd == "FLIP" and len(set(CASHTAG_RX.findall(st["quote"] or ""))) >= 3:
        review.append({**v, "_skip": "x_multi_cashtag_roundup_ambiguous"}); continue
    if vd == "FLIP":
        cd = (v.get("corrected_direction") or "").lower()
        if cd in ("bullish", "bearish") and cd != (st["direction"] or "").lower():
            flips.append((v, st)); continue
        review.append({**v, "_skip": "flip_noop_or_invalid_dir"}); continue
    if vd == "RETICKER":
        ct = (v.get("correct_ticker") or "").upper()
        if ct and SYM.match(ct) and ct != (st["ticker"] or "").upper() and ct in UNIVERSE:
            rets.append((v, st)); continue
        review.append({**v, "_skip": "reticker_unvalidated_or_noop", "_target": ct,
                       "_in_universe": ct in UNIVERSE}); continue
    review.append({**v, "_skip": "keep_or_ambiguous"})

print(f"verdicts: {len(verds)} | FLIP-apply={len(flips)} RETICKER-apply={len(rets)} review={len(review)}")
from collections import Counter
print("  FLIP dirs:", dict(Counter(v['corrected_direction'] for v, _ in flips)))
print("  scored rows among flips/retickers (score-impacting):",
      sum(1 for _, st in flips + rets if st["outcome"] in ("hit", "miss", "near")))
print("  review reasons:", dict(Counter(r.get('_skip') for r in review)))

# snapshot BEFORE state for the rows we will mutate (reversibility)
apply_ids = [v["id"] for v, _ in flips] + [v["id"] for v, _ in rets]
cur.execute("""SELECT id,ticker,direction,outcome,entry_price::float,actual_return::float,
                      evaluated_at::text FROM predictions WHERE id = ANY(%s)""", (apply_ids,))
before = {r[0]: {"ticker": r[1], "direction": r[2], "outcome": r[3], "entry": r[4],
                 "ret": r[5], "evaluated_at": r[6]} for r in cur.fetchall()}

os.makedirs(os.path.dirname(REVIEW), exist_ok=True)
json.dump(review, open(REVIEW, "w"), indent=1)

if not COMMIT:
    print(f"\nDRY-RUN: no writes. review JSON -> {REVIEW}")
    print("re-run with --commit to apply + snapshot.")
    conn.close(); sys.exit(0)

json.dump(before, open(SNAP, "w"), indent=1)

FLIP_SQL = """UPDATE predictions SET direction=%s, outcome='pending', evaluated_at=NULL,
  evaluation_summary='['||%s||' opus FLIP '||direction||'->'||%s||'; [pre_remediation] outcome='
    ||COALESCE(outcome,'?')||' entry='||COALESCE(entry_price::text,'?')||' ret='||COALESCE(actual_return::text,'?')||'] '
    ||COALESCE(evaluation_summary,'')
  WHERE id=%s AND COALESCE(evaluation_summary,'') NOT LIKE '%%'||%s||'%%'"""
RET_SQL = """UPDATE predictions SET ticker=%s, entry_price=NULL, outcome='pending', evaluated_at=NULL,
  evaluation_summary='['||%s||' opus RETICKER '||ticker||'->'||%s||'; [pre_remediation] outcome='
    ||COALESCE(outcome,'?')||' entry='||COALESCE(entry_price::text,'?')||' ret='||COALESCE(actual_return::text,'?')||'] '
    ||COALESCE(evaluation_summary,'')
  WHERE id=%s AND COALESCE(evaluation_summary,'') NOT LIKE '%%'||%s||'%%'"""

nf = nr = 0
for v, st in flips:
    cur.execute(FLIP_SQL, (v["corrected_direction"], MARK, v["corrected_direction"], v["id"], MARK)); nf += cur.rowcount
for v, st in rets:
    ct = v["correct_ticker"].upper()
    cur.execute(RET_SQL, (ct, MARK, ct, v["id"], MARK)); nr += cur.rowcount
conn.commit()
json.dump({"flip_ids": [v["id"] for v, _ in flips], "ret_ids": [v["id"] for v, _ in rets]},
          open(APPLIED, "w"))
print(f"\nAPPLIED: FLIP={nf}/{len(flips)}  RETICKER={nr}/{len(rets)}")
print(f"snapshot -> {SNAP}\napplied ids -> {APPLIED}")
print("NEXT: re-score via evaluate_batch, then balanced-transition check. Do NOT re-run this script.")
conn.close()
