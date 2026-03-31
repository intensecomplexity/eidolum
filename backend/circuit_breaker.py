"""
Circuit breaker for background jobs — prevents DB overload from killing the site.

Before any background job touches the database, call `db_is_healthy()`.
If the DB is slow or unreachable, the job skips this cycle and retries next time.

Also provides:
- Global job lock: only ONE background job runs at a time
- Auto-pause: if user-facing queries are slow, ALL jobs pause for 15 minutes
- Watchdog: auto-kills jobs stuck for more than 10 minutes
- Memory guard: skips batches when memory is low
"""
import os
import time
import threading
from datetime import datetime, timedelta

# ── State ──────────────────────────────────────────────────────────────────────
_jobs_paused_until: datetime | None = None
_pause_lock = threading.Lock()
_running_jobs: dict[str, datetime] = {}
_running_lock = threading.Lock()

PAUSE_DURATION_MINUTES = 5
DB_HEALTH_TIMEOUT_SECONDS = 3.0
DB_HEALTH_SLOW_THRESHOLD_SECONDS = 3.0

# Track consecutive self-check failures (only pause after 3 in a row)
_selfcheck_failures = 0

# ── PROTECTION 2: Global job lock ─────────────────────────────────────────────
# Only ONE background job can run at any time. If a second job tries to start
# while one is already running, it skips this cycle.
_job_lock = threading.Lock()
_job_lock_holder: str | None = None
_job_lock_acquired_at: datetime | None = None
_job_lock_meta_lock = threading.Lock()  # protects the metadata above


def acquire_job_lock(job_name: str) -> bool:
    """Try to acquire the global job lock. Returns True if acquired, False if another job holds it."""
    acquired = _job_lock.acquire(blocking=False)
    if acquired:
        with _job_lock_meta_lock:
            global _job_lock_holder, _job_lock_acquired_at
            _job_lock_holder = job_name
            _job_lock_acquired_at = datetime.utcnow()
        print(f"[JobLock] {job_name}: acquired global lock")
        return True
    else:
        with _job_lock_meta_lock:
            holder = _job_lock_holder
        print(f"[JobLock] {job_name}: SKIPPED — lock held by {holder}")
        return False


def release_job_lock(job_name: str):
    """Release the global job lock."""
    with _job_lock_meta_lock:
        global _job_lock_holder, _job_lock_acquired_at
        _job_lock_holder = None
        _job_lock_acquired_at = None
    try:
        _job_lock.release()
    except RuntimeError:
        pass  # already released (e.g. by watchdog)
    print(f"[JobLock] {job_name}: released global lock")


def get_job_lock_status() -> dict:
    """Return current global lock state for diagnostics."""
    with _job_lock_meta_lock:
        holder = _job_lock_holder
        acquired_at = _job_lock_acquired_at
    locked = _job_lock.locked()
    duration = None
    if acquired_at:
        duration = (datetime.utcnow() - acquired_at).total_seconds()
    return {
        "locked": locked,
        "holder": holder,
        "acquired_at": acquired_at.isoformat() if acquired_at else None,
        "duration_seconds": round(duration, 1) if duration else None,
    }


# ── PROTECTION 6: Watchdog — auto-kill stuck jobs ─────────────────────────────
STUCK_JOB_TIMEOUT_SECONDS = 600  # 10 minutes


def watchdog_check():
    """Force-release the global lock if a job has been running for more than 10 minutes.
    Run this on a 5-minute schedule."""
    with _job_lock_meta_lock:
        holder = _job_lock_holder
        acquired_at = _job_lock_acquired_at

    if not holder or not acquired_at:
        return

    elapsed = (datetime.utcnow() - acquired_at).total_seconds()
    if elapsed > STUCK_JOB_TIMEOUT_SECONDS:
        print(f"[Watchdog] FORCE-RELEASING lock held by {holder} for {elapsed:.0f}s (>{STUCK_JOB_TIMEOUT_SECONDS}s)")
        release_job_lock(f"watchdog(was:{holder})")
        # Also clear it from running jobs tracking
        mark_job_done(holder)


# ── PROTECTION 7: Memory guard ────────────────────────────────────────────────
MEMORY_MIN_MB = 100


def memory_is_available() -> bool:
    """Check if at least MEMORY_MIN_MB of memory is free. Skip batch if not."""
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    available_kb = int(line.split()[1])
                    available_mb = available_kb / 1024
                    if available_mb < MEMORY_MIN_MB:
                        print(f"[MemGuard] Only {available_mb:.0f}MB free (<{MEMORY_MIN_MB}MB), skipping batch")
                        return False
                    return True
    except Exception:
        pass  # /proc/meminfo not available (non-Linux), assume OK
    return True


# ── STORAGE GUARD: Skip data ingestion if DB approaching volume limit ─────────
DB_SIZE_LIMIT_BYTES = 40 * 1024 * 1024 * 1024  # 40 GB (volume is 50 GB, leaves 10 GB for WAL/temp)
_last_storage_check: float = 0
_last_storage_ok: bool = True
STORAGE_CHECK_INTERVAL = 300  # Re-check every 5 minutes, not every job


def db_storage_ok(job_name: str = "unknown") -> bool:
    """Check if the database size is under the safety limit.
    Caches the result for 5 minutes to avoid hammering pg_database_size."""
    global _last_storage_check, _last_storage_ok

    now = time.time()
    if now - _last_storage_check < STORAGE_CHECK_INTERVAL:
        if not _last_storage_ok:
            print(f"[StorageGuard] {job_name}: SKIPPED — storage limit approaching (cached)")
        return _last_storage_ok

    try:
        from database import bg_engine
        from sqlalchemy import text as _t

        with bg_engine.connect() as conn:
            row = conn.execute(_t("SELECT pg_database_size(current_database())")).scalar()
            size_bytes = int(row)
            size_gb = size_bytes / (1024 ** 3)

        _last_storage_check = now

        if size_bytes > DB_SIZE_LIMIT_BYTES:
            _last_storage_ok = False
            print(f"[StorageGuard] {job_name}: SKIPPED — DB is {size_gb:.2f}GB (limit {DB_SIZE_LIMIT_BYTES / (1024**3):.0f}GB). Pausing data ingestion.")
            return False

        _last_storage_ok = True
        return True

    except Exception as e:
        # If we can't check, allow the job to proceed (don't block on check failure)
        print(f"[StorageGuard] {job_name}: check failed ({e}), allowing job")
        _last_storage_check = now
        _last_storage_ok = True
        return True


# ── Circuit breaker DB health check ───────────────────────────────────────────
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

    # PROTECTION 3: Run a test query with tight timeout
    try:
        from database import bg_engine
        from sqlalchemy import text as _t

        start = time.time()
        with bg_engine.connect() as conn:
            conn.execute(_t("SELECT 1"))
        elapsed = time.time() - start

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
        "job_lock": get_job_lock_status(),
    }


def check_site_health_and_pause():
    """Check if user-facing endpoints are slow; if so, pause background jobs.

    Only pauses after 3 consecutive failures to avoid false positives from
    transient network issues (common on Railway/container platforms).
    """
    global _selfcheck_failures
    import httpx

    try:
        start = time.time()
        port = int(os.environ.get("PORT", 8000))
        r = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=5)
        elapsed = time.time() - start

        if elapsed > 4.0 or r.status_code != 200:
            _selfcheck_failures += 1
            print(f"[HealthCheck] Slow/failed ({elapsed:.1f}s, status={r.status_code}), failures={_selfcheck_failures}/3")
            if _selfcheck_failures >= 3:
                pause_all_jobs(f"3 consecutive health check failures")
                _selfcheck_failures = 0
        else:
            _selfcheck_failures = 0  # Reset on success
    except Exception as e:
        _selfcheck_failures += 1
        print(f"[HealthCheck] Self-check error: {e}, failures={_selfcheck_failures}/3")
        if _selfcheck_failures >= 3:
            pause_all_jobs(f"3 consecutive self-check errors")
            _selfcheck_failures = 0
