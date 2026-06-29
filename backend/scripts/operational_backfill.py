"""PHASE 5 — operational backfill. Re-extract operational claims over the 4 gold rows +
a keyword-filtered population sample, populate the migration-0025 fields, route them off
the price path (evaluation_deferred=TRUE — the existing "owned by a different scorer"
mechanism, so evaluator.py is NOT touched), then score the ones whose period has passed
via jobs.operational_evaluator. Reversible: before-state of every touched row is snapshotted.

Run:  DATABASE_URL=$DATABASE_PUBLIC_URL python3 scripts/operational_backfill.py [SAMPLE_LIMIT]
Reads predictions; writes ONLY the operational columns (+ outcome on scored rows).
"""
import os, sys, json, datetime
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text as sql
from database import BgSessionLocal
from scripts.operational_extractor import extract_operational
from jobs.operational_evaluator import score_operational

GOLD = [] if os.environ.get("BACKFILL_OLD") else [607205, 609156, 634843, 630302]
SAMPLE_LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("SAMPLE_LIMIT", "25"))
_suffix = "_old" if os.environ.get("BACKFILL_OLD") else ""
ART = os.path.join(os.path.dirname(__file__), f"operational_backfill_results{_suffix}.json")
SNAP = os.path.join(os.path.dirname(__file__), "operational_backfill_before_snapshot.json")
KW = "%(free cash flow|revenue|cash flow|earnings per share| eps |net income|margin|cagr|gross profit|operating income|guidance)%"


def candidates(db):
    rows = {}
    for r in db.execute(sql("""
        SELECT id, ticker, direction, prediction_date,
               COALESCE(NULLIF(source_verbatim_quote,''), exact_quote, context, '') AS q
        FROM predictions WHERE id = ANY(:ids)"""), {"ids": GOLD}):
        rows[r.id] = dict(r._mapping)
    # BACKFILL_OLD=1 targets older predictions (prediction_date <= 2024-06) ordered oldest
    # first — those are more likely to reference a fiscal period that has now been reported,
    # so the scorer can resolve some to hit/miss rather than all-pending.
    old = os.environ.get("BACKFILL_OLD")
    date_clause = "AND prediction_date <= DATE '2024-06-01'" if old else ""
    order = "prediction_date ASC" if old else "id DESC"
    extra = db.execute(sql(f"""
        SELECT id, ticker, direction, prediction_date,
               COALESCE(NULLIF(source_verbatim_quote,''), exact_quote, context, '') AS q
        FROM predictions
        WHERE COALESCE(claim_type,'price')='price'
          AND id <> ALL(:ids)
          AND COALESCE(NULLIF(source_verbatim_quote,''), exact_quote, context, '') ~* :kw
          AND length(COALESCE(NULLIF(source_verbatim_quote,''), exact_quote, context, '')) > 25
          {date_clause}
        ORDER BY {order} LIMIT :lim"""), {"ids": GOLD, "kw": KW.strip("%"), "lim": SAMPLE_LIMIT})
    for r in extra:
        rows.setdefault(r.id, dict(r._mapping))
    return list(rows.values())


def main():
    db = BgSessionLocal()
    cand = candidates(db)
    print(f"candidates: {len(cand)} ({len(GOLD)} gold + up to {SAMPLE_LIMIT} sample). extracting via claude -p...", flush=True)

    def do_extract(c):
        return c, extract_operational(c["ticker"], c["q"])
    with ThreadPoolExecutor(max_workers=2) as ex:
        extracted = list(ex.map(do_extract, cand))

    before, results = [], []
    op_rows = []
    for c, e in extracted:
        ct = (e.get("claim_type") or "").lower()
        rec = {"id": c["id"], "ticker": c["ticker"], "claim_type": ct,
               "metric": e.get("metric"), "kind": e.get("metric_kind"),
               "target": e.get("target_value"), "period": e.get("target_period"),
               "error": e.get("_error")}
        if ct == "operational" and e.get("metric") and e.get("metric_kind"):
            op_rows.append((c, e))
        results.append(rec)

    # snapshot + write operational fields, route off price path
    scored = {"hit": 0, "near": 0, "miss": 0}
    pending = 0
    for c, e in op_rows:
        cur = db.execute(sql("""SELECT id, claim_type, metric_type, metric_kind, metric_target_value,
                   metric_target_period, metric_actual_value, metric_resolved_at, outcome,
                   evaluation_deferred, direction FROM predictions WHERE id=:i"""), {"i": c["id"]}).fetchone()
        snap = dict(cur._mapping)
        for k, v in list(snap.items()):
            if isinstance(v, (datetime.date, datetime.datetime)):
                snap[k] = v.isoformat()
        before.append(snap)
        new_dir = c["direction"] or (e.get("direction") if e.get("metric_kind") == "direction" else None)
        db.execute(sql("""UPDATE predictions SET
              claim_type='operational', metric_type=:m, metric_kind=:k,
              metric_target_value=:tv, metric_target_period=:tp,
              evaluation_deferred=TRUE, direction=COALESCE(direction,:d)
            WHERE id=:i"""),
            {"m": e["metric"], "k": e["metric_kind"],
             "tv": (float(e["target_value"]) if e.get("target_value") is not None else None),
             "tp": e.get("target_period"), "d": new_dir, "i": c["id"]})
        # score
        prow = db.execute(sql("""SELECT ticker, direction, claim_type, metric_type, metric_kind,
                   metric_target_value, metric_target_period, prediction_date
                   FROM predictions WHERE id=:i"""), {"i": c["id"]}).fetchone()
        res = score_operational(dict(prow._mapping), db=db)
        out = next(r for r in results if r["id"] == c["id"])
        out["score_status"] = res["status"]
        out["outcome"] = res.get("outcome")
        out["reason"] = res.get("reason")
        if res["status"] == "scored":
            db.execute(sql("""UPDATE predictions SET outcome=:o, metric_actual_value=:av,
                       metric_resolved_at=:ra WHERE id=:i"""),
                {"o": res["outcome"], "av": res["metric_actual_value"],
                 "ra": res["metric_resolved_at"], "i": c["id"]})
            scored[res["outcome"]] = scored.get(res["outcome"], 0) + 1
            out["actual"] = (res.get("detail") or {}).get("actual") or (res.get("detail") or {}).get("actual_pct")
        else:
            db.execute(sql("UPDATE predictions SET outcome='pending' WHERE id=:i"), {"i": c["id"]})
            pending += 1
    db.commit()

    # append to the before-snapshot (dedup by id) so reversibility survives multiple passes
    prior = json.load(open(SNAP)) if os.path.exists(SNAP) else []
    seen = {r["id"] for r in prior}
    prior.extend(r for r in before if r["id"] not in seen)
    json.dump(prior, open(SNAP, "w"), indent=1)
    n_scored = sum(scored.values())
    summary = {"candidates": len(cand), "operational_tagged": len(op_rows),
               "scored": n_scored, "pending": pending, "scored_breakdown": scored,
               "hit_rate": (round(scored["hit"] / n_scored, 3) if n_scored else None),
               "rows": results}
    json.dump(summary, open(ART, "w"), indent=1)
    print(f"\n=== PHASE 5 BACKFILL ===")
    print(f" candidates={len(cand)}  operational_tagged={len(op_rows)}  scored={n_scored} {scored}  pending={pending}")
    print(f" hit_rate(scored)={summary['hit_rate']}")
    for r in results:
        if r["claim_type"] == "operational":
            print(f"  [{r['id']}] {r['ticker']:5} {r['metric']}/{r['kind']} tgt={r['target']} per={r['period']} "
                  f"-> {r.get('score_status')} {r.get('outcome') or r.get('reason')}")
    print(f" snapshot -> {SNAP}\n results -> {ART}")


if __name__ == "__main__":
    main()
