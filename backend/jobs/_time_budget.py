"""
Time-budget helper for long-running maintenance jobs.

Every maintenance job (logos, backfills, harvests) MUST self-terminate after
30 minutes max per run. This protects against bugs we haven't found yet —
memory leaks, DB connection leaks, API runaway loops, etc.

Usage:
    from jobs._time_budget import TimeBudget, TimeBudgetExceeded

    def my_maintenance_job():
        try:
            with TimeBudget(seconds=1800, job_name='MyJob') as budget:
                for item in big_list:
                    budget.check()  # raises TimeBudgetExceeded if over budget
                    do_work(item)
        except TimeBudgetExceeded:
            # Clean exit, scheduler will retry on next interval
            return
"""
import time
import logging

log = logging.getLogger(__name__)

DEFAULT_BUDGET_SECONDS = 1800  # 30 minutes


class TimeBudgetExceeded(Exception):
    """Raised by TimeBudget.check() when the time budget is exhausted."""


class TimeBudget:
    def __init__(self, seconds: int = DEFAULT_BUDGET_SECONDS, job_name: str = "unknown"):
        self.seconds = seconds
        self.job_name = job_name
        self.start = None

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        return False  # don't swallow exceptions

    def elapsed(self) -> float:
        return time.time() - (self.start or time.time())

    def remaining(self) -> float:
        return max(0.0, self.seconds - self.elapsed())

    def should_stop(self) -> bool:
        return self.elapsed() >= self.seconds

    def check(self):
        """Raises TimeBudgetExceeded if over budget. Call from inside loops."""
        if self.should_stop():
            log.info(
                f"[{self.job_name}] Time budget of {self.seconds}s reached, stopping cleanly"
            )
            raise TimeBudgetExceeded(
                f"{self.job_name} exceeded {self.seconds}s budget"
            )
