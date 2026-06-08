"""Real-data precision analysis for classifier Rules 11-14 at 50K scale.

Read-only. Pulls the most recent 50K predictions that carry a
source_verbatim_quote and runs each shadow rule against them, reporting the
would-reject count (activity) and a sample for manual precision judgement.

Rule 12 additionally needs the video publish date, which is NOT a column on
`predictions`; it is resolved via the documented JOIN
  predictions.transcript_video_id -> youtube_videos.youtube_video_id (.published_at)
This mirrors the caller-level JOIN that the live plumbing performs.

Usage: DATABASE_PUBLIC_URL=... python3 backend/scripts/realdata_rules_11_14_precision.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "jobs"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text  # noqa: E402
import classifier_validation as gate  # noqa: E402

DBURL = (os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
         or os.environ.get("DBURL"))
if not DBURL:
    print("No DB URL", file=sys.stderr)
    sys.exit(2)

LIMIT = int(os.environ.get("SAMPLE_LIMIT", "50000"))

eng = create_engine(DBURL)


def _col_exists(db, table, col):
    return db.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name=:t AND column_name=:c"), {"t": table, "c": col}).first() is not None


with eng.connect() as db:
    cols = {c: _col_exists(db, "predictions", c) for c in
            ("source_verbatim_quote", "transcript_video_id", "prediction_date",
             "inferred_timeframe_days", "timeframe_category")}
    print("predictions columns present:", cols)
    yv_pub = _col_exists(db, "youtube_videos", "publish_date")
    print("youtube_videos.publish_date present:", yv_pub)

    # Base pull: rows with a verbatim quote, most recent first.
    base_sql = (
        "SELECT id, ticker, direction, source_verbatim_quote, "
        "       prediction_date, inferred_timeframe_days, timeframe_category, "
        "       transcript_video_id "
        "FROM predictions "
        "WHERE source_verbatim_quote IS NOT NULL "
        "  AND length(trim(source_verbatim_quote)) > 0 "
        "ORDER BY id DESC LIMIT :lim"
    )
    rows = db.execute(text(base_sql), {"lim": LIMIT}).fetchall()
    print(f"\nPulled {len(rows)} rows with verbatim quotes (most recent {LIMIT}).")

    # Build a video_id -> published_at map for the Rule 12 JOIN.
    vids = {r.transcript_video_id for r in rows if r.transcript_video_id}
    pub_map = {}
    if vids and yv_pub:
        vid_list = list(vids)
        for i in range(0, len(vid_list), 1000):
            chunk = vid_list[i:i + 1000]
            for vr in db.execute(text(
                "SELECT youtube_video_id, publish_date FROM youtube_videos "
                "WHERE youtube_video_id = ANY(:ids)"), {"ids": chunk}).fetchall():
                pub_map[vr[0]] = vr[1]
    print(f"Resolved publish dates for {len(pub_map)}/{len(vids)} distinct videos.\n")

    counters = {"rule_11": [], "rule_12": [], "rule_13": [], "rule_14": []}
    rule12_eligible = 0
    rule12_date_differs = 0  # prediction_date != publish_date among eligible

    for r in rows:
        q = r.source_verbatim_quote
        # Rule 11
        if not gate.check_question_rhetorical(q)[0]:
            counters["rule_11"].append((r.ticker, q))
        # Rule 13 — pass db for alias resolution (production parity)
        if not gate.check_basket_too_broad(q, r.ticker, db)[0]:
            counters["rule_13"].append((r.ticker, q))
        # Rule 14
        if not gate.check_news_recap(q)[0]:
            counters["rule_14"].append((r.ticker, q))
        # Rule 12 — needs prediction_date + video publish date + horizon
        vp = pub_map.get(r.transcript_video_id)
        if r.prediction_date is not None and vp is not None:
            rule12_eligible += 1
            pd_ = gate._to_date(r.prediction_date)
            vp_ = gate._to_date(vp)
            if pd_ != vp_:
                rule12_date_differs += 1
            if not gate.check_date_passed(
                    r.prediction_date, vp, None,
                    r.inferred_timeframe_days, r.timeframe_category)[0]:
                counters["rule_12"].append((r.ticker, q))

    n = len(rows)
    print("=" * 72)
    print(f"REAL-DATA ACTIVITY over {n} rows")
    print("=" * 72)
    for rk, hits in counters.items():
        rate = (len(hits) / n * 100) if n else 0
        extra = ""
        if rk == "rule_12":
            extra = (f"  (eligible rows with both dates: {rule12_eligible}; "
                     f"prediction_date != publish_date: {rule12_date_differs})")
        print(f"{rk}: would-reject {len(hits)}  ({rate:.3f}% of {n}){extra}")

    for rk, hits in counters.items():
        print("\n" + "-" * 72)
        print(f"{rk} — up to 30 sample would-rejects (manual precision check):")
        for tk, q in hits[:30]:
            print(f"  [{tk}] {(q or '')[:220]}")
