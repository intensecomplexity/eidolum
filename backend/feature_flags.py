"""
Feature flags read from the `config` table.

Lazy, dependency-free helpers so any job or router can ask the question without
having to know the underlying schema.
"""
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
