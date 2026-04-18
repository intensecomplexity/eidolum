"""One-shot: populate predictions.generating_model from verified_by.

Idempotent — re-running only touches rows where generating_model is
still NULL. Safe to run multiple times.

Backfill source is verified_by (set by the classifier at insert time),
NOT created_at. The classifier stamps verified_by='youtube_haiku_v1'
even after the Qwen cutover when the RunPod endpoint times out and
the pipeline falls back to Haiku — a timestamp-only rule mis-tags
those 506 post-cutover Haiku rows as Qwen.

Run:
    DATABASE_URL=... python3 backend/scripts/backfill_generating_model.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg2  # noqa: E402


MAPPING = (
    ("haiku",        "youtube_haiku_v1"),
    ("qwen_lora_v1", "youtube_qwen_v1"),
)


def main() -> int:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    try:
        total_updated = 0
        for model, verified_by in MAPPING:
            cur.execute("""
                UPDATE predictions
                SET generating_model = %s
                WHERE generating_model IS NULL
                  AND verified_by = %s
            """, (model, verified_by))
            updated = cur.rowcount or 0
            total_updated += updated
            print(f"  {model:<15}  {updated:>7,} rows updated "
                  f"(where verified_by = {verified_by!r})")
        conn.commit()

        # Final state report
        cur.execute("""
            SELECT COALESCE(generating_model, '(null)'), COUNT(*)
            FROM predictions
            WHERE source_type = 'youtube'
            GROUP BY 1 ORDER BY 2 DESC
        """)
        print()
        print("  YouTube rows by generating_model:")
        for r in cur.fetchall():
            print(f"    {r[0]:<15}  {r[1]:>7,}")

        cur.execute("""
            SELECT COALESCE(generating_model, '(null)'), COUNT(*)
            FROM predictions
            GROUP BY 1 ORDER BY 2 DESC
        """)
        print()
        print("  All predictions by generating_model:")
        for r in cur.fetchall():
            print(f"    {r[0]:<15}  {r[1]:>7,}")

        print()
        print(f"  total rows updated this run: {total_updated:,}")
        return 0
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {type(e).__name__}: {e}")
        return 1
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
