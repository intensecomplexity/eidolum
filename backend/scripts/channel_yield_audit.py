"""Auto-cull low-yield YouTube channels.

Computes per-channel prediction yield over the last 90 days and
soft-deactivates channels that classify plenty of videos but almost
never produce a ticker-level prediction.

Yield metric (clean yield): denominator is videos that were ACTUALLY
classified — transcript_status in ('ok_inserted','ok_no_predictions').
Videos that errored (classifier_error, transcript-fetch failures,
shorts_skipped) are excluded — a 0% yield caused by a transcript bug is
not a content signal and must not trigger a cull.

Cull rule: clean_videos >= 20 AND clean_yield_pct < 5%  ->  CULL.

Soft-deactivate only (is_active=FALSE, deactivation_reason=
'auto_cull_low_yield'). The monitor's _seed_target_channels re-activate
phase is patched to leave this reason alone, so the cull survives
without editing TARGET_CHANNELS. Fully reversible — see the restore SQL
printed at the end.

Usage:
    python3 scripts/channel_yield_audit.py            # dry run (report only)
    python3 scripts/channel_yield_audit.py --apply    # deactivate the cull list
"""
import ast
import os
import re
import sys

import psycopg2

WINDOW_DAYS = 90
MIN_CLEAN_VIDEOS = 20
YIELD_CULL_PCT = 5.0

# Channels that must never be auto-culled even if they meet the rule —
# strategically important or otherwise valued. Empty for the initial run.
PROTECTED_CHANNELS = [
]

DBURL = (os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
         or os.environ.get("DBURL"))
_MONITOR = os.path.join(os.path.dirname(__file__), "..", "jobs",
                        "youtube_channel_monitor.py")


def _target_channels():
    src = open(_MONITOR).read()
    m = re.search(r'TARGET_CHANNELS = (\[.*?\n\])', src, re.S)
    return ast.literal_eval(m.group(1))


def main():
    apply = "--apply" in sys.argv
    targets = _target_channels()
    conn = psycopg2.connect(DBURL)
    cur = conn.cursor()

    # videos per channel per transcript_status (last 90d)
    cur.execute(f"""SELECT channel_name, transcript_status, count(*)
        FROM youtube_videos
        WHERE processed_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
        GROUP BY 1, 2""")
    vid = {}
    for ch, st, n in cur.fetchall():
        vid.setdefault(ch, {})[st or "NULL"] = n

    # predictions linked to those videos
    cur.execute(f"""SELECT v.channel_name, count(*)
        FROM predictions p
        JOIN youtube_videos v ON v.youtube_video_id = p.transcript_video_id
        WHERE v.processed_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
          AND p.source_type = 'youtube'
        GROUP BY 1""")
    preds = {ch: n for ch, n in cur.fetchall()}

    cur.execute(f"""SELECT channel_name, min(processed_at), max(processed_at)
        FROM youtube_videos
        WHERE processed_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
        GROUP BY 1""")
    dates = {ch: (a, b) for ch, a, b in cur.fetchall()}

    rows = []
    for ch in targets:
        sc = vid.get(ch, {})
        clean = sc.get("ok_inserted", 0) + sc.get("ok_no_predictions", 0)
        p = preds.get(ch, 0)
        first, last = dates.get(ch, (None, None))
        y = (100.0 * p / clean) if clean else None
        rows.append({"channel": ch, "clean": clean, "preds": p,
                     "yield": y, "first": first, "last": last})

    rows.sort(key=lambda r: (r["yield"] is None,
                             r["yield"] if r["yield"] is not None else 1e9))

    print(f"=== Clean-yield audit — last {WINDOW_DAYS} days, "
          f"{len(targets)} TARGET_CHANNELS ===")
    print(f"{'CHANNEL':40s} {'classified':>10s} {'preds':>6s} "
          f"{'yield%':>7s}  last_processed")
    print("-" * 86)
    cull, spared = [], []
    for r in rows:
        ymark = f"{r['yield']:.1f}" if r["yield"] is not None else "  n/a"
        eligible = r["clean"] >= MIN_CLEAN_VIDEOS and r["yield"] is not None \
            and r["yield"] < YIELD_CULL_PCT
        if eligible and r["channel"] in PROTECTED_CHANNELS:
            spared.append(r); tag = "  <-- SPARED (protected)"
        elif eligible:
            cull.append(r); tag = "  <-- CULL"
        else:
            tag = ""
        print(f"{r['channel']:40s} {r['clean']:10d} {r['preds']:6d} "
              f"{ymark:>7s}  {str(r['last'])[:16]}{tag}")

    print(f"\n=== CULL LIST: {len(cull)} channels "
          f"(clean>={MIN_CLEAN_VIDEOS} AND yield<{YIELD_CULL_PCT}%) ===")
    for r in cull:
        print(f"  {r['channel']:40s} classified={r['clean']} preds={r['preds']} "
              f"yield={r['yield']:.1f}% last={str(r['last'])[:10]}")
    if spared:
        print(f"\n=== SPARED by PROTECTED_CHANNELS: {len(spared)} ===")
        for r in spared:
            print(f"  {r['channel']}")
    else:
        print("\n=== SPARED by PROTECTED_CHANNELS: 0 (list is empty) ===")

    cur.execute("SELECT count(*) FROM youtube_channels WHERE is_active = TRUE")
    active_before = cur.fetchone()[0]
    print(f"\nyoutube_channels active before: {active_before}")

    if not apply:
        print("\n[DRY RUN] re-run with --apply to soft-deactivate the cull list.")
        conn.close()
        return 0

    names = [r["channel"] for r in cull]
    cur.execute("""UPDATE youtube_channels
        SET is_active = FALSE, deactivated_at = NOW(),
            deactivation_reason = 'auto_cull_low_yield'
        WHERE channel_name = ANY(%s) AND is_active = TRUE""", (names,))
    flipped = cur.rowcount
    conn.commit()
    cur.execute("SELECT count(*) FROM youtube_channels WHERE is_active = TRUE")
    active_after = cur.fetchone()[0]
    print(f"\n[APPLIED] soft-deactivated {flipped} channels "
          f"(reason='auto_cull_low_yield')")
    print(f"youtube_channels active after: {active_after}")
    print("\nRestore command (un-cull everything from this run):")
    print("  UPDATE youtube_channels SET is_active = TRUE, "
          "deactivated_at = NULL, deactivation_reason = NULL")
    print("  WHERE deactivation_reason = 'auto_cull_low_yield';")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
