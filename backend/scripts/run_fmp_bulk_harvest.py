"""
run_fmp_bulk_harvest.py — driver for the dormant fmp_bulk_harvest job.

The job at backend/jobs/fmp_bulk_harvest.py defines run_fmp_bulk_harvest(db)
which populates 9 high-value reference tables (company_profiles,
analyst_consensus, price_target_summary, stock_ratings, earnings_history,
stock_peers, key_metrics, earnings_surprises, sector_performance) from
FMP bulk endpoints. It was committed but never wired into the worker
scheduler (commented out at worker.py:2321 as `# sched.add_job(..._fmp_harvest...)`).

This driver lets us populate those tables manually during the FMP Ultimate
window so the data persists after the plan downgrades. Run from the laptop:

    cd ~/quantanalytics/backend
    DATABASE_URL=$(railway variables --service Postgres --json | \\
        python3 -c "import sys,json;print(json.load(sys.stdin)['DATABASE_PUBLIC_URL'])")
    FMP_KEY=$(railway variables --service hopeful-expression --json | \\
        python3 -c "import sys,json;print(json.load(sys.stdin)['FMP_KEY'])")
    DATABASE_URL="$DB_URL" FMP_KEY="$FMP_KEY" python3 -m scripts.run_fmp_bulk_harvest
"""
import os
import sys

if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import BgSessionLocal
from jobs.fmp_bulk_harvest import run_fmp_bulk_harvest


def main():
    db = BgSessionLocal()
    try:
        run_fmp_bulk_harvest(db)
    finally:
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
