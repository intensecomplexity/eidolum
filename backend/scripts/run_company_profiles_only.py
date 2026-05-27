"""
run_company_profiles_only.py — driver for just harvest_company_profiles.

Wave 2's company_profiles came up partial (FMP rate-limited profile-bulk
after the audit pulled it twice in quick succession). This driver runs
ONLY the profile harvest so we can retry after the cooldown without
re-pulling the other 7 tables.

Chained from a probe-loop bash wrapper that watches for profile-bulk to
return HTTP 200 + non-trivial body.
"""
import os
import sys

if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import BgSessionLocal
from jobs.fmp_bulk_harvest import harvest_company_profiles


def main():
    db = BgSessionLocal()
    try:
        n = harvest_company_profiles(db)
        print(f"[run_company_profiles_only] inserted/updated: {n:,}", flush=True)
    finally:
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
