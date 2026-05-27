"""Shared SQL-fragment helpers for user-facing prediction endpoints.

Per [[project_eidolum_hypothetical_handling]] three-tier policy, Tier 2
hedged/hypothetical predictions stay in the data layer for transparency
but are hidden from user-facing list / aggregation endpoints.

The HIDE_HEDGED_PREDICTIONS env var is the kill switch — flip to off
via Railway env vars without redeploying:

    railway variables --service eidolum --set HIDE_HEDGED_PREDICTIONS=false

Defaults to ON so the launch ships with the filter active.
"""
import os

HIDE_HEDGED_PREDICTIONS = (
    os.environ.get("HIDE_HEDGED_PREDICTIONS", "on").lower()
    in ("on", "true", "1", "yes")
)


def hedged_filter_sql(table_alias: str = "p") -> str:
    """Return an ``AND``-prefixed SQL fragment that filters out hedged /
    hypothetical predictions when ``HIDE_HEDGED_PREDICTIONS`` is enabled.
    Returns an empty string when disabled, so callers can interpolate
    unconditionally.

    NULL ``conviction_level`` is preserved — 98%+ of historical predictions
    pre-date metadata enrichment and carry NULL conviction; the filter
    targets only EXPLICITLY hedged or hypothetical rows.

    Usage::

        cur.execute(f'''
            SELECT ... FROM predictions p
            WHERE outcome != 'pending' {hedged_filter_sql()}
        ''')
    """
    if not HIDE_HEDGED_PREDICTIONS:
        return ""
    return (
        f" AND ({table_alias}.conviction_level NOT IN ('hedged', 'hypothetical') "
        f"OR {table_alias}.conviction_level IS NULL)"
    )
