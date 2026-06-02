"""Shared SQL-fragment helpers for user-facing prediction endpoints.

Per [[project_eidolum_hypothetical_handling]] three-tier policy, Tier 2
hedged/hypothetical predictions stay in the data layer for transparency
but are hidden from user-facing list / aggregation endpoints. The
2026-06-02 reported-speech audit added a second visibility class: rows
whose source quote is third-party attribution ("analysts expect X",
"consensus price target", "<firm> analyst") rather than the speaker's
own conviction call. Those rows are flagged `is_reported_speech=TRUE`
and hidden from the same surfaces.

Both filters share the same call-site pattern. `hedged_filter_sql` /
`hedged_filter_clause` bundle BOTH visibility checks so the dozen+
existing call sites pick up reported-speech hiding without per-site
edits. Each filter has an independent kill switch env var so they can
be flipped separately at runtime:

    railway variables --service eidolum --set HIDE_HEDGED_PREDICTIONS=false
    railway variables --service eidolum --set HIDE_REPORTED_SPEECH=false

Both default ON so the launch ships with hiding active.
"""
import os

HIDE_HEDGED_PREDICTIONS = (
    os.environ.get("HIDE_HEDGED_PREDICTIONS", "on").lower()
    in ("on", "true", "1", "yes")
)

HIDE_REPORTED_SPEECH = (
    os.environ.get("HIDE_REPORTED_SPEECH", "on").lower()
    in ("on", "true", "1", "yes")
)


def reported_speech_filter_sql(table_alias: str = "p") -> str:
    """Return an ``AND``-prefixed SQL fragment that excludes rows flagged
    as reported speech (third-party attribution).

    Shape (active):
        AND COALESCE(<alias>.is_reported_speech, FALSE) = FALSE
    """
    if not HIDE_REPORTED_SPEECH:
        return ""
    return (
        f" AND COALESCE({table_alias}.is_reported_speech, FALSE) = FALSE"
    )


def hedged_filter_sql(table_alias: str = "p") -> str:
    """Return an ``AND``-prefixed SQL fragment that filters out hedged /
    hypothetical predictions AND reported-speech predictions when their
    respective env-var kill switches are enabled.

    Returns an empty string when both are disabled, so callers can
    interpolate unconditionally.

    NULL ``conviction_level`` is preserved on the hedged check — 98%+
    of historical predictions pre-date metadata enrichment and carry
    NULL conviction; the filter targets only EXPLICITLY hedged or
    hypothetical rows. The reported-speech check uses ``COALESCE`` so
    rows pre-dating the 2026-06-02 audit column pass through.

    Usage::

        cur.execute(f'''
            SELECT ... FROM predictions p
            WHERE outcome != 'pending' {hedged_filter_sql()}
        ''')
    """
    parts = []
    if HIDE_HEDGED_PREDICTIONS:
        parts.append(
            f" AND ({table_alias}.conviction_level NOT IN ('hedged', 'hypothetical') "
            f"OR {table_alias}.conviction_level IS NULL)"
        )
    if HIDE_REPORTED_SPEECH:
        parts.append(
            f" AND COALESCE({table_alias}.is_reported_speech, FALSE) = FALSE"
        )
    return "".join(parts)


def reported_speech_filter_clause(reported_attr):
    """ORM equivalent of ``reported_speech_filter_sql``. Pass the model
    attribute (e.g. ``Prediction.is_reported_speech``). Returns a
    ``true`` clause when the kill switch is off so the call site can
    chain unconditionally."""
    if not HIDE_REPORTED_SPEECH:
        from sqlalchemy import true
        return true()
    from sqlalchemy import or_
    return or_(reported_attr.is_(False), reported_attr.is_(None))


def hedged_filter_clause(conviction_attr):
    """ORM equivalent of ``hedged_filter_sql`` for SQLAlchemy ``.filter()``
    chains. Pass the conviction-level model attribute (e.g.
    ``Prediction.conviction_level``) and chain unconditionally — when
    the env var is off the helper returns a ``true`` clause so the
    filter is a no-op and the call site doesn't need an ``if`` guard.

    NOTE: this clause covers ONLY hedged/hypothetical. Call sites that
    use the ORM equivalent should chain
    ``reported_speech_filter_clause(Prediction.is_reported_speech)``
    alongside to match the SQL helper's combined semantics.

    Usage::

        from routers._prediction_filters import (
            hedged_filter_clause, reported_speech_filter_clause,
        )
        from models import Prediction

        query.filter(
            hedged_filter_clause(Prediction.conviction_level),
            reported_speech_filter_clause(Prediction.is_reported_speech),
        )
    """
    if not HIDE_HEDGED_PREDICTIONS:
        from sqlalchemy import true
        return true()
    from sqlalchemy import or_
    return or_(
        conviction_attr.notin_(['hedged', 'hypothetical']),
        conviction_attr.is_(None),
    )
