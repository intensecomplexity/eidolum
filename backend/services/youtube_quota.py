"""
YouTube API v3 quota tracker and safety system.
Daily quota: 10,000 units. Costs:
- search.list = 100 units (NEVER use this)
- playlistItems.list = 1 unit (use for fetching videos)
- channels.list = 1 unit
- videos.list = 1 unit
"""
import os
import datetime

DAILY_LIMIT = 10000
SAFETY_THRESHOLD = int(os.getenv("YOUTUBE_QUOTA_SAFETY_THRESHOLD", "8000"))
SYNC_INTERVAL_HOURS = int(os.getenv("YOUTUBE_SYNC_INTERVAL_HOURS", "6"))
MAX_VIDEOS_PER_SYNC = int(os.getenv("YOUTUBE_MAX_VIDEOS_PER_SYNC", "50"))


class QuotaTracker:
    def __init__(self):
        self.used_today = 0
        self.reset_date = datetime.date.today()
        self.log = []  # in-memory log, also persisted to DB

    def _maybe_reset(self):
        today = datetime.date.today()
        if today > self.reset_date:
            self.used_today = 0
            self.reset_date = today
            self.log = []

    def can_make_request(self, cost: int) -> bool:
        self._maybe_reset()
        return (self.used_today + cost) < SAFETY_THRESHOLD

    def track(self, endpoint: str, cost: int):
        self._maybe_reset()
        self.used_today += cost
        self.log.append({
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "endpoint": endpoint,
            "units": cost,
            "total_today": self.used_today,
        })

    def safe_request(self, endpoint: str, cost: int, fn, fallback=None):
        """Execute fn() if quota allows, otherwise return fallback. Never crashes."""
        if not self.can_make_request(cost):
            print(f"QUOTA SAFETY: Skipping {endpoint}, {self.used_today}/{SAFETY_THRESHOLD} units used today")
            return fallback
        try:
            result = fn()
            self.track(endpoint, cost)
            return result
        except Exception as e:
            print(f"YouTube API error ({endpoint}): {e}")
            return fallback

    def get_status(self) -> dict:
        self._maybe_reset()
        # Aggregate top consumers
        consumer_map = {}
        for entry in self.log:
            ep = entry["endpoint"]
            consumer_map[ep] = consumer_map.get(ep, 0) + entry["units"]
        top_consumers = sorted(
            [{"endpoint": k, "units": v} for k, v in consumer_map.items()],
            key=lambda x: x["units"],
            reverse=True,
        )

        used = self.used_today
        if used >= SAFETY_THRESHOLD:
            status = "blocked"
        elif used >= SAFETY_THRESHOLD * 0.7:
            status = "warning"
        else:
            status = "healthy"

        return {
            "units_used_today": used,
            "daily_limit": DAILY_LIMIT,
            "safety_threshold": SAFETY_THRESHOLD,
            "status": status,
            "reset_date": self.reset_date.isoformat(),
            "top_consumers": top_consumers[:10],
        }


# Singleton
quota = QuotaTracker()
