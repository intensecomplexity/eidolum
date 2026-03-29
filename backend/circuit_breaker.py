"""
Circuit breaker for background jobs — prevents DB overload from killing the site.

Before any background job touches the database, call `db_is_healthy()`.
If the DB is slow or unreachable, the job skips this cycle and retries next time.

Also provides auto-pause: if user-facing queries are slow, ALL background jobs
pause for 15 minutes automatically.
"""
import time
import threading
from datetime import datetime, timedelta

# ── State ──────────────────────────────────────────────────────────────────────
_jobs_paused_until: datetime | None = None
_pause_lock = threading.Lock()
_running_jobs: dict[str, datetime] = {}
_running_lock = threading.Lock()

PAUSE_DURATION_MINUTES = 15
DB_HEALTH_TIMEOUT_SECONDS = 2.0
DB_HEALTH_SLOW_THRESHOLD_SECONDS = 1.0


def db_is_healthy(job_name: str = "unknown") -> bool:
    """Check if the database is responsive enough for a background job to proceed.

    Returns True if the job should run, False if it should skip this cycle.
    Call this at the TOP of every background job, before any DB work.
    """
    # Check if jobs are auto-paused
    with _pause_lock:
        if _jobs_paused_until and datetime.utcnow() < _jobs_paused_until:
            remaining = (_jobs_paused_until - datetime.utcnow()).seconds
            print(f"[CircuitBreaker] {job_name}: SKIPPED — jobs paused for {remaining}s more")
            return False

    # Run a test query with tight timeout
    try:
        from database import BgSessionLocal
        from sqlalchemy import text as _t

        start = time.time()
        db = BgSessionLocal()
        try:
            db.execute(_t("SELECT 1"))
            elapsed = time.time() - start
        finally:
            db.close()

        if elapsed > DB_HEALTH_SLOW_THRESHOLD_SECONDS:
            print(f"[CircuitBreaker] {job_name}: SKIPPED — DB responded in {elapsed:.1f}s (>{DB_HEALTH_SLOW_THRESHOLD_SECONDS}s)")
            return False

        return True

    except Exception as e:
        print(f"[CircuitBreaker] {job_name}: SKIPPED — DB unreachable: {e}")
        return False


def pause_all_jobs(reason: str = ""):
    """Pause all background jobs for PAUSE_DURATION_MINUTES."""
    global _jobs_paused_until
    with _pause_lock:
        _jobs_paused_until = datetime.utcnow() + timedelta(minutes=PAUSE_DURATION_MINUTES)
    print(f"[CircuitBreaker] ALL JOBS PAUSED for {PAUSE_DURATION_MINUTES}min — {reason}")


def resume_all_jobs():
    """Manually resume jobs early."""
    global _jobs_paused_until
    with _pause_lock:
        _jobs_paused_until = None
    print("[CircuitBreaker] Jobs resumed manually")


def mark_job_running(job_name: str):
    """Track that a job is currently executing."""
    with _running_lock:
        _running_jobs[job_name] = datetime.utcnow()


def mark_job_done(job_name: str):
    """Track that a job has finished executing."""
    with _running_lock:
        _running_jobs.pop(job_name, None)


def get_running_jobs() -> dict[str, str]:
    """Return currently running jobs with their start times."""
    with _running_lock:
        return {k: v.isoformat() for k, v in _running_jobs.items()}


def get_status() -> dict:
    """Full circuit breaker status for diagnostics."""
    with _pause_lock:
        paused = _jobs_paused_until is not None and datetime.utcnow() < _jobs_paused_until
        paused_until = _jobs_paused_until.isoformat() if _jobs_paused_until else None

    return {
        "jobs_paused": paused,
        "paused_until": paused_until,
        "running_jobs": get_running_jobs(),
        "pause_duration_minutes": PAUSE_DURATION_MINUTES,
        "db_slow_threshold_seconds": DB_HEALTH_SLOW_THRESHOLD_SECONDS,
    }


def check_site_health_and_pause():
    """Check if user-facing endpoints are slow; if so, pause background jobs.

    This is meant to run on a schedule (every 5 minutes).
    """
    import httpx

    try:
        start = time.time()
        # Use internal request to avoid going through external load balancer
        port = int(os.environ.get("PORT", 8000))
        r = httpx.get(f"http://127.0.0.1:{port}/api/homepage-stats", timeout=5)
        elapsed = time.time() - start

        if elapsed > 3.0:
            pause_all_jobs(f"homepage-stats took {elapsed:.1f}s")
        elif r.status_code != 200:
            pause_all_jobs(f"homepage-stats returned {r.status_code}")
    except Exception as e:
        # If we can't even reach ourselves, definitely pause
        pause_all_jobs(f"self-check failed: {e}")


import os  # needed by check_site_health_and_pause
