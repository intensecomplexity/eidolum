"""One-off purge: delete YouTube predictions that landed without a
resolved source_timestamp_seconds.

Context: before the hard-gate shipped in youtube_classifier, a bug in
the transcript pipeline could allow ticker predictions to be inserted
without a timestamp match, which makes the deep-link (&t=XXs) on the
prediction card unrenderable. This script removes those rows and also
un-marks the source video in youtube_videos so the next backfill cycle
re-pulls the transcript and re-classifies with timestamps.

Run:
    cd backend && railway run python3 scripts/purge_no_timestamp.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402

REPROCESS_VIDEO_IDS = ("1MtuSMIH8gE",)

# Note: Forecaster has no source_type column — that lives on the
# predictions row itself (source_type='youtube'). The `status` column
# in the spec is the `outcome` column on the Prediction model.
SELECT_SQL = text("""
    SELECT p.id, p.ticker, p.forecaster_id, p.source_url,
           p.source_timestamp_seconds, p.created_at
    FROM predictions p
    WHERE p.source_type = 'youtube'
      AND (p.source_timestamp_seconds IS NULL
           OR p.source_timestamp_seconds = 0)
      AND p.outcome = 'pending'
    ORDER BY p.created_at DESC NULLS LAST
""")

DELETE_SQL = text("""
    DELETE FROM predictions
    WHERE id IN (
        SELECT p.id
        FROM predictions p
        WHERE p.source_type = 'youtube'
          AND (p.source_timestamp_seconds IS NULL
               OR p.source_timestamp_seconds = 0)
          AND p.outcome = 'pending'
    )
""")


def main() -> int:
    db = SessionLocal()
    try:
        rows = db.execute(SELECT_SQL).fetchall()
        print(f"Found {len(rows)} YouTube predictions missing "
              f"source_timestamp_seconds and still pending.")
        for r in rows[:25]:
            print(f"  id={r[0]:>7}  {r[1]:<6}  fid={r[2]:<6}  "
                  f"ts={r[4]}  created={r[5]}  {r[3]}")
        if len(rows) > 25:
            print(f"  ... and {len(rows) - 25} more")

        if not rows:
            print("Nothing to delete. Still running youtube_videos unmark step.")

        result = db.execute(DELETE_SQL)
        deleted = result.rowcount or 0
        print(f"Deleted {deleted} predictions.")

        for vid in REPROCESS_VIDEO_IDS:
            r = db.execute(text(
                "DELETE FROM youtube_videos WHERE youtube_video_id = :vid"
            ), {"vid": vid})
            print(f"youtube_videos unmark {vid}: removed {r.rowcount or 0} row(s).")

        db.commit()
        print("Committed.")
        return 0
    except Exception as e:
        db.rollback()
        print(f"ERROR: {type(e).__name__}: {e}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
