"""Re-window + re-score the historical "said long-term, scored <=90d" rows.

Follow-up to the 2026-06-12 horizon-mismatch audit and the
long_horizon_rule prompt ship (423c109). The audit's regex+transcript
scan over visible YouTube ticker_calls with window_days<=90 produced 722
candidates; a per-row claude -p Sonnet judge (3-way, conservative
default-N, same prompt as the audit + an explicit stated-horizon probe)
confirmed the Y set embedded below. N and U rows are untouched.

For every judge-Y row (id-pinned in Y_ROWS, idempotent via the
timeframe_source provenance tag):
  1. Re-window: window_days = stated speaker horizon if explicitly longer
     (e.g. "5 years" -> 1825; the TMO precedent) else 365;
     inferred_timeframe_days mirrors it; timeframe_category =
     'long_term_fundamental'; timeframe_source = 'lh_remediation_2026_06_12' (provenance;
     <=32 chars — the column is varchar(32)).
  2. Re-score, evaluator-faithfully, from LOCAL price_bars only:
     - already-SCORED rows (hit/correct/near/miss/incorrect, entry_price
       present) whose new window has MATURED: recompute outcome at the
       closest bar to prediction_date+window (+/-10d). Tolerances are the
       evaluator's own 365-row (HIT 10 / NEAR-min 4); target rows use the
       real target/tolerance branch, no-target rows are sign-based,
       neutral uses the 5/10 bands. actual_return is direction-adjusted
       and bounded_return-clamped; alpha recomputed vs SPY price_bars.
     - scored rows NOT yet mature at the new window: revert to pending
       (outcome='pending', actual_return/evaluation_date NULL) — the
       organic evaluator scores them at maturity.
     - no price_bars coverage at the new exit: window corrected, outcome
       left untouched (counted + listed).
     - pending/unresolved/delisted/no_data rows: window corrected only.
  3. Reversibility: BEFORE any overwrite the original
     {outcome, actual_return, window_days, evaluation_date} is appended
     to evaluation_summary as a [pre_remediation] JSON note.

NO DELETEs. NO hiding. After running, refresh forecaster stats
server-side (railway ssh --service eidolum -> refresh_all_forecaster_stats;
the X-Admin-Secret curl path is dead — ADMIN_SECRET is empty on the API).

Usage:
  DATABASE_PUBLIC_URL=... python3 backend/scripts/remediate_long_horizon_windows_2026_06_12.py          # dry run
  DATABASE_PUBLIC_URL=... python3 backend/scripts/remediate_long_horizon_windows_2026_06_12.py --apply
"""
import datetime
import json
import os
import sys

import psycopg2
import psycopg2.extras

TAG = "lh_remediation_2026_06_12"  # <=32 chars: timeframe_source is varchar(32)
TODAY = datetime.date(2026, 6, 12)
TOL, MINMOV = 10.0, 4.0          # evaluator _TOLERANCE/_MIN_MOVEMENT, >=365 bucket
SCORED = ("hit", "correct", "near", "miss", "incorrect")

# id -> new window_days (365 unless the speaker stated a longer explicit
# horizon). Generated from /tmp/.lhrem/judge_full.jsonl (722 candidates,
# verdict counts in the ship report); regenerate via the audit pipeline.
Y_ROWS = {
    605603: 365, 605622: 365, 605627: 365, 605640: 3650, 605641: 365, 605683: 365,
    605687: 1825, 605734: 365, 605880: 365, 605946: 365, 605951: 3650, 605957: 365,
    605958: 365, 605969: 365, 606009: 730, 606028: 365, 606037: 365, 606038: 365,
    606047: 365, 606069: 365, 606110: 365, 606112: 365, 606113: 365, 606114: 365,
    606271: 365, 606277: 365, 606288: 365, 606314: 365, 606335: 365, 606362: 365,
    606363: 365, 606384: 365, 606392: 365, 606397: 365, 606400: 365, 606416: 730,
    606432: 1460, 606437: 365, 606441: 365, 606453: 1825, 606454: 365, 606462: 365,
    606471: 365, 606485: 365, 606495: 365, 606497: 365, 606521: 365, 606582: 365,
    606597: 365, 606598: 365, 606609: 365, 606628: 365, 606630: 365, 606632: 365,
    606634: 365, 606649: 365, 606650: 365, 606668: 365, 606670: 365, 606672: 365,
    606673: 365, 606674: 365, 606682: 365, 606683: 365, 606685: 365, 606694: 365,
    606700: 365, 606709: 365, 606719: 365, 606734: 365, 606735: 365, 606737: 365,
    606739: 365, 606764: 365, 606767: 365, 606770: 365, 606771: 365, 606783: 365,
    606784: 365, 606818: 365, 606819: 365, 606820: 365, 606823: 365, 606824: 365,
    606828: 365, 606845: 365, 606857: 365, 606912: 365, 607018: 365, 607036: 365,
    607074: 365, 607076: 365, 607077: 365, 607089: 365, 607285: 365, 607320: 365,
    607436: 365, 607437: 365, 607439: 365, 607940: 365, 607958: 365, 607960: 365,
    608068: 365, 608463: 365, 608465: 365, 608862: 365, 608911: 730, 609016: 365,
    609097: 1095, 609433: 365, 609665: 365, 610586: 365, 610654: 365, 610923: 365,
    611047: 365, 611056: 365, 611888: 912, 611890: 365, 612215: 365, 612216: 365,
    612969: 365, 612971: 365, 612972: 365, 612973: 365, 612974: 365, 613730: 365,
    613738: 365, 614003: 365, 614012: 365, 614085: 365, 614129: 365, 614147: 365,
    614171: 365, 614176: 365, 614178: 365, 614180: 365, 614246: 365, 614650: 365,
    614791: 365, 615025: 365, 616171: 365, 617043: 365, 617160: 365, 619149: 365,
    621602: 365, 622262: 365, 624019: 365, 624580: 365, 624980: 365, 625046: 365,
    625047: 365, 625076: 365, 625078: 365, 625079: 365, 625120: 365, 625144: 1825,
    625150: 365, 625160: 3650, 625163: 365, 625171: 365, 625181: 365, 625204: 365,
    625207: 1825, 625208: 1825, 625258: 365, 625259: 3650, 625262: 365, 625264: 365,
    625268: 365, 625270: 365, 625272: 365, 625282: 365, 625283: 365, 625286: 365,
    625288: 365, 625289: 365, 625290: 365, 625298: 365, 626104: 365, 626441: 365,
    627073: 365, 627074: 365, 627172: 730, 627472: 365, 627487: 365, 628528: 365,
    628968: 365, 629320: 365, 629347: 365, 629425: 365, 630687: 1825, 630953: 365,
    631100: 365,
}


def bounded(ret, window):
    cap = 200.0 if window > 180 else (150.0 if window > 90 else 100.0)
    return max(-100.0, min(cap, ret))


def main():
    apply = "--apply" in sys.argv
    url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print("set DATABASE_PUBLIC_URL"); sys.exit(2)
    conn = psycopg2.connect(url)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    counts = {"window_only": 0, "rescored": 0, "to_pending": 0,
              "no_coverage": 0, "already_done": 0, "flips": []}
    affected_fids = set()

    for pid, new_window in sorted(Y_ROWS.items()):
        cur.execute("""SELECT id, ticker, direction, outcome, actual_return,
            entry_price, target_price, prediction_date, evaluation_date,
            window_days, forecaster_id, timeframe_source, evaluation_summary
            FROM predictions WHERE id=%s""", (pid,))
        r = cur.fetchone()
        if not r:
            print(f"  {pid}: MISSING — skipped"); continue
        if r["timeframe_source"] == TAG:
            counts["already_done"] += 1; continue
        affected_fids.add(r["forecaster_id"])

        pre = json.dumps({"pre_remediation": {
            "outcome": r["outcome"],
            "actual_return": float(r["actual_return"]) if r["actual_return"] is not None else None,
            "window_days": r["window_days"],
            "evaluation_date": str(r["evaluation_date"]) if r["evaluation_date"] else None}})
        summary = (r["evaluation_summary"] or "") + f"\n[{TAG}] " + pre

        sets = ["window_days=%s", "inferred_timeframe_days=%s",
                "timeframe_category='long_term_fundamental'",
                "timeframe_source=%s", "evaluation_summary=%s"]
        vals = [new_window, new_window, TAG, summary]

        scored = r["outcome"] in SCORED and r["entry_price"] is not None
        if scored:
            pd_ = r["prediction_date"].date()
            exit_target = pd_ + datetime.timedelta(days=new_window)
            if exit_target > TODAY:
                sets += ["outcome='pending'", "actual_return=NULL",
                         "evaluation_date=NULL", "alpha=NULL"]
                counts["to_pending"] += 1
                tagline = "to_pending"
            else:
                cur.execute("""SELECT bar_date, close FROM price_bars
                    WHERE ticker=%s AND bar_date BETWEEN %s AND %s
                    ORDER BY ABS(bar_date - %s) LIMIT 1""",
                    (r["ticker"], exit_target - datetime.timedelta(days=10),
                     exit_target + datetime.timedelta(days=10), exit_target))
                bar = cur.fetchone()
                if not bar:
                    counts["no_coverage"] += 1
                    tagline = "no_coverage (window corrected, outcome untouched)"
                else:
                    entry = float(r["entry_price"]); ev = float(bar["close"])
                    raw = round((ev - entry) / entry * 100, 2)
                    d = r["direction"]
                    tgt = float(r["target_price"]) if r["target_price"] else None
                    if d == "neutral":
                        a = abs(raw)
                        new_out = "hit" if a <= 5 else ("near" if a <= 10 else "miss")
                    elif tgt and tgt > 0:
                        dist = abs(ev - tgt) / tgt * 100
                        if d == "bullish":
                            new_out = ("hit" if (ev >= tgt or (dist <= TOL and raw >= 0))
                                       else "near" if raw >= MINMOV else "miss")
                        else:
                            new_out = ("hit" if (ev <= tgt or (dist <= TOL and raw <= 0))
                                       else "near" if raw <= -MINMOV else "miss")
                    else:
                        new_out = ("hit" if (ev > entry if d == "bullish" else ev < entry)
                                   else "miss")
                    ret = bounded(-raw if d == "bearish" else raw, new_window)
                    # alpha vs SPY over the same span, from local bars
                    alpha = None
                    cur.execute("""SELECT close FROM price_bars WHERE ticker='SPY'
                        AND bar_date BETWEEN %s AND %s ORDER BY ABS(bar_date-%s) LIMIT 1""",
                        (pd_ - datetime.timedelta(days=10), pd_ + datetime.timedelta(days=10), pd_))
                    s0 = cur.fetchone()
                    cur.execute("""SELECT close FROM price_bars WHERE ticker='SPY'
                        AND bar_date BETWEEN %s AND %s ORDER BY ABS(bar_date-%s) LIMIT 1""",
                        (bar["bar_date"] - datetime.timedelta(days=10),
                         bar["bar_date"] + datetime.timedelta(days=10), bar["bar_date"]))
                    s1 = cur.fetchone()
                    if s0 and s1 and float(s0["close"]) > 0:
                        spy_ret = round((float(s1["close"]) - float(s0["close"]))
                                        / float(s0["close"]) * 100, 2)
                        alpha = round(ret - spy_ret, 2)
                    sets += ["outcome=%s", "actual_return=%s",
                             "evaluation_date=%s", "alpha=%s", "evaluated_at=NOW()"]
                    vals += [new_out, ret, bar["bar_date"], alpha]
                    counts["rescored"] += 1
                    old_b = "hit" if r["outcome"] in ("hit", "correct") else (
                        "near" if r["outcome"] == "near" else "miss")
                    if old_b != new_out:
                        counts["flips"].append(
                            f"{pid} {r['ticker']} {old_b}->{new_out} ret={ret}")
                    tagline = f"rescored {old_b}->{new_out} ret={ret}"
        else:
            counts["window_only"] += 1
            tagline = f"window_only (outcome={r['outcome']})"

        print(f"  {pid} {r['ticker']} window {r['window_days']}->{new_window}: {tagline}")
        if apply:
            cur.execute(f"UPDATE predictions SET {', '.join(sets)} WHERE id=%s",
                        vals + [pid])

    if apply:
        conn.commit()
        print("\nCOMMITTED.")
    else:
        conn.rollback()
        print("\nDRY RUN — rolled back. Re-run with --apply.")
    counts["flips_n"] = len(counts["flips"])
    print(json.dumps({k: v for k, v in counts.items() if k != "flips"}, indent=1))
    for f in counts["flips"]:
        print("  FLIP", f)
    print(f"affected forecasters: {sorted(affected_fids)}")


if __name__ == "__main__":
    main()
