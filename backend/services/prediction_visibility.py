"""Shared visibility filter for user-facing prediction queries.

Policy (2026-04-18): YouTube predictions that lack a resolved
``source_timestamp_seconds`` must NOT appear on any user-facing
surface and must NOT count toward cached forecaster stats (accuracy,
alpha, avg_return, XP). They stay in the ``predictions`` table —
the youtube_timestamp_backfill worker UPDATEs ``source_timestamp_seconds``
in place, and as soon as the value goes from NULL to an int, the row
becomes visible and countable automatically.

Admin / internal surfaces (e.g. /admin/*, scripts under backend/scripts)
bypass this filter so operators can audit the backfill queue. Scoring
jobs that populate ``outcome`` / ``actual_return`` also bypass — those
need to process the row BEFORE visibility, so scores are ready the
moment a timestamp lands.

Usage:
    from services.prediction_visibility import yt_visible_filter

    where = f"WHERE forecaster_id = :fid AND {yt_visible_filter('p')}"

The helper takes an optional table alias ("p" by default). When a
query references ``predictions`` without an alias, pass ``alias=""``
and the leading dot is omitted.
"""
from __future__ import annotations


def yt_visible_filter(alias: str = "p") -> str:
    """Return a SQL fragment that excludes legacy YouTube predictions
    with NULL source_timestamp_seconds. Safe to paste into any WHERE
    clause with a leading ``AND``.

    Shape:
        NOT (<alias>.source_type = 'youtube'
             AND <alias>.source_timestamp_seconds IS NULL)

    Non-YouTube rows pass regardless. YouTube rows with a real
    timestamp pass. YouTube rows with NULL timestamp are excluded.
    """
    prefix = f"{alias}." if alias else ""
    return (
        f"NOT ({prefix}source_type = 'youtube' "
        f"AND {prefix}source_timestamp_seconds IS NULL)"
    )


# Bare-table form for queries that don't use an alias
YT_VISIBLE_FILTER_SQL = yt_visible_filter("")
