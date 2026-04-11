"""
Feature flags read from the `config` table.

Lazy, dependency-free helpers so any job or router can ask the question without
having to know the underlying schema.
"""
import hashlib
import time
from sqlalchemy import text as sql_text


def _read_bool(db, key: str, default: bool) -> bool:
    try:
        row = db.execute(
            sql_text("SELECT value FROM config WHERE key = :k"),
            {"k": key},
        ).first()
    except Exception:
        return default
    if not row or row[0] is None:
        return default
    return str(row[0]).strip().lower() == "true"


def _read_int(db, key: str, default: int) -> int:
    try:
        row = db.execute(
            sql_text("SELECT value FROM config WHERE key = :k"),
            {"k": key},
        ).first()
    except Exception:
        return default
    if not row or row[0] is None:
        return default
    try:
        return int(str(row[0]).strip())
    except (ValueError, TypeError):
        return default


def is_x_evaluation_enabled(db) -> bool:
    """When false, evaluators must skip predictions with source_type='x' and
    forecaster stats aggregations must exclude them. Default false: X
    predictions stay outcome='pending' until an admin flips this on."""
    return _read_bool(db, "EVALUATE_X_PREDICTIONS", default=False)


def x_filter_sql(db, *, table_alias: str | None = None) -> str:
    """Return ' AND <alias.>source_type IS DISTINCT FROM ''x''' when X
    evaluation is disabled, else empty string. Always safe to splice into a
    WHERE clause that already has at least one condition."""
    if is_x_evaluation_enabled(db):
        return ""
    prefix = f"{table_alias}." if table_alias else ""
    return f" AND {prefix}source_type IS DISTINCT FROM 'x'"


# ── YouTube sector-call traffic routing ─────────────────────────────────────
#
# ENABLE_YOUTUBE_SECTOR_CALLS is an integer 0-100 storing the traffic
# percentage that should use the sector-aware Haiku prompt. 0 = feature
# OFF entirely. 10 = 10% of videos routed to the new prompt. 100 = every
# video uses it. Default 0: the new prompt never runs in production
# until an admin flips the flag from the /admin/dashboard Overview tab.
#
# Routing is STABLE by video_id: hash(video_id) % 100 < traffic_pct.
# The same video always routes to the same prompt regardless of retries,
# which guarantees no flakiness across re-processing.

_YT_SECTOR_TRAFFIC_CACHE: dict = {"pct": 0, "fetched_at": 0.0}
_YT_SECTOR_TRAFFIC_TTL = 60  # seconds


def get_youtube_sector_traffic_pct(db) -> int:
    """Return the current traffic percentage (0-100) for the YouTube
    sector-call prompt. Cached for 60 seconds so a tight monitor loop
    doesn't hammer the config table."""
    now = time.time()
    if (now - _YT_SECTOR_TRAFFIC_CACHE["fetched_at"]) < _YT_SECTOR_TRAFFIC_TTL:
        return int(_YT_SECTOR_TRAFFIC_CACHE["pct"])
    pct = _read_int(db, "ENABLE_YOUTUBE_SECTOR_CALLS", default=0)
    if pct < 0:
        pct = 0
    if pct > 100:
        pct = 100
    _YT_SECTOR_TRAFFIC_CACHE["pct"] = pct
    _YT_SECTOR_TRAFFIC_CACHE["fetched_at"] = now
    return pct


def should_use_sector_prompt(db, video_id: str | None) -> bool:
    """Stable routing: given a video_id, return True if this video should
    use the sector-aware Haiku prompt. The same video always routes to
    the same prompt (MD5 hash mod 100 compared to the traffic pct) so
    retries are deterministic.

    Returns False unconditionally when:
      - video_id is missing/empty (can't hash)
      - traffic pct is 0 (feature off)
    Returns True unconditionally when traffic pct is 100.
    """
    if not video_id:
        return False
    pct = get_youtube_sector_traffic_pct(db)
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    bucket = int(hashlib.md5(str(video_id).encode("utf-8")).hexdigest(), 16) % 100
    return bucket < pct


def map_sector_to_etf(db, sector_text: str | None) -> str | None:
    """Look up a free-form sector label in sector_etf_aliases and return
    the mapped ETF ticker, or None if not found. Case-insensitive,
    whitespace-trimmed. Used by the YouTube classifier to convert a
    Haiku-extracted sector_call into a real ticker for the predictions
    table.

    Fail-safe: if the table doesn't exist yet or the query errors,
    returns None (callers log a 'sector_etf_unknown' rejection).
    """
    if not sector_text:
        return None
    cleaned = str(sector_text).strip().lower()
    if not cleaned:
        return None
    try:
        row = db.execute(
            sql_text(
                "SELECT etf_ticker FROM sector_etf_aliases "
                "WHERE LOWER(alias) = :a LIMIT 1"
            ),
            {"a": cleaned},
        ).first()
    except Exception:
        return None
    if not row:
        return None
    return str(row[0]).upper() if row[0] else None


def invalidate_sector_traffic_cache() -> None:
    """Reset the 60-second cache — called from the admin endpoint that
    changes the traffic percentage so the new value takes effect
    immediately without waiting for the TTL to expire."""
    _YT_SECTOR_TRAFFIC_CACHE["fetched_at"] = 0.0


# ── Ranked list extraction flag ─────────────────────────────────────────────
#
# Boolean all-or-nothing flag (not a traffic percentage). When false, the
# YouTube classifier does NOT append the ranked-list instructions to the
# Haiku system prompt, so list_id / list_rank stay NULL on every new row.
# Cached for 60 seconds to avoid hammering the config table in tight loops.

_RANKED_LIST_FLAG_CACHE: dict = {"enabled": False, "fetched_at": 0.0}
_RANKED_LIST_FLAG_TTL = 60  # seconds


def is_ranked_list_extraction_enabled(db) -> bool:
    """Return True if ENABLE_RANKED_LIST_EXTRACTION is set to 'true' in
    the config table. Default False. Cached 60s."""
    now = time.time()
    if (now - _RANKED_LIST_FLAG_CACHE["fetched_at"]) < _RANKED_LIST_FLAG_TTL:
        return bool(_RANKED_LIST_FLAG_CACHE["enabled"])
    enabled = _read_bool(db, "ENABLE_RANKED_LIST_EXTRACTION", default=False)
    _RANKED_LIST_FLAG_CACHE["enabled"] = enabled
    _RANKED_LIST_FLAG_CACHE["fetched_at"] = now
    return enabled


def invalidate_ranked_list_flag_cache() -> None:
    """Reset the 60-second cache — called from the admin toggle endpoint
    so the new value takes effect immediately."""
    _RANKED_LIST_FLAG_CACHE["fetched_at"] = 0.0


# ── Target revisions flag ───────────────────────────────────────────────────
#
# Boolean all-or-nothing flag. When true, the YouTube classifier appends
# the revision-detection instructions to the Haiku system prompt so
# statements like "moving my AAPL target from $200 to $220" extract as
# is_revision=true predictions and the insertion path links them to
# their immediate predecessor via the revision_of FK.

_TARGET_REVISIONS_FLAG_CACHE: dict = {"enabled": False, "fetched_at": 0.0}
_TARGET_REVISIONS_FLAG_TTL = 60  # seconds


def is_target_revisions_enabled(db) -> bool:
    """Return True if ENABLE_TARGET_REVISIONS is 'true' in config.
    Default False. Cached 60s to avoid hammering the config table in
    tight loops (classifier runs per-video-per-chunk)."""
    now = time.time()
    if (now - _TARGET_REVISIONS_FLAG_CACHE["fetched_at"]) < _TARGET_REVISIONS_FLAG_TTL:
        return bool(_TARGET_REVISIONS_FLAG_CACHE["enabled"])
    enabled = _read_bool(db, "ENABLE_TARGET_REVISIONS", default=False)
    _TARGET_REVISIONS_FLAG_CACHE["enabled"] = enabled
    _TARGET_REVISIONS_FLAG_CACHE["fetched_at"] = now
    return enabled


def invalidate_target_revisions_flag_cache() -> None:
    """Reset the 60-second cache — called from the admin toggle endpoint
    so changes take effect immediately instead of waiting for the TTL."""
    _TARGET_REVISIONS_FLAG_CACHE["fetched_at"] = 0.0


# ── Options position extraction flag ────────────────────────────────────────
#
# Boolean all-or-nothing flag. When true, the YouTube classifier appends
# the options-position instruction block to the Haiku system prompt so
# options vocabulary ("buying $200 calls on AAPL", "selling puts on NVDA",
# "iron condor on SPY") gets mapped to an equivalent ticker_call with
# the correct direction and (when available) strike as target_price.
# Options-derived predictions are NOT a new category — they land as
# prediction_category='ticker_call' in the database. The counter on
# scraper_runs.options_positions_extracted tracks extraction volume.

_OPTIONS_EXTRACTION_FLAG_CACHE: dict = {"enabled": False, "fetched_at": 0.0}
_OPTIONS_EXTRACTION_FLAG_TTL = 60  # seconds


def is_options_extraction_enabled(db) -> bool:
    """Return True if ENABLE_OPTIONS_POSITION_EXTRACTION is 'true' in
    the config table. Default False. Cached 60s to avoid hammering the
    config table in tight classifier loops (one check per video chunk)."""
    now = time.time()
    if (now - _OPTIONS_EXTRACTION_FLAG_CACHE["fetched_at"]) < _OPTIONS_EXTRACTION_FLAG_TTL:
        return bool(_OPTIONS_EXTRACTION_FLAG_CACHE["enabled"])
    enabled = _read_bool(db, "ENABLE_OPTIONS_POSITION_EXTRACTION", default=False)
    _OPTIONS_EXTRACTION_FLAG_CACHE["enabled"] = enabled
    _OPTIONS_EXTRACTION_FLAG_CACHE["fetched_at"] = now
    return enabled


def invalidate_options_extraction_flag_cache() -> None:
    """Reset the 60-second cache — called from the admin toggle endpoint
    so changes take effect immediately instead of waiting for the TTL."""
    _OPTIONS_EXTRACTION_FLAG_CACHE["fetched_at"] = 0.0
