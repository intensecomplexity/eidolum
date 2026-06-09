"""Product-theme query helpers.

Themes are the second, overlapping navigation axis alongside sectors:
hand-curated MANY-TO-MANY ticker memberships ('Phones' spans AAPL +
GOOGL + QCOM; QCOM is also in 'AI Chips'). v1 is filter + tag only —
every helper here resolves a theme to its member tickers at query time
so a future scored axis can aggregate over the same membership with no
schema change.

All fragments keep the theme slug as a BOUND parameter — never
string-interpolate slugs or ticker lists into SQL.
"""
from sqlalchemy import text as sql_text


def get_theme_tickers(db, slug_or_id) -> list[str]:
    """Return the member tickers for a theme, by slug (str) or id (int).
    Inactive themes return an empty list."""
    if isinstance(slug_or_id, int):
        where, param = "t.id = :key", slug_or_id
    else:
        where, param = "t.slug = :key", str(slug_or_id)
    rows = db.execute(sql_text(f"""
        SELECT tt.ticker
        FROM theme_tickers tt
        JOIN themes t ON t.id = tt.theme_id
        WHERE {where} AND t.is_active
        ORDER BY tt.is_primary DESC, tt.ticker
    """), {"key": param}).fetchall()
    return [r[0] for r in rows]


def get_ticker_themes(db, ticker: str) -> list[dict]:
    """Return the active themes a ticker belongs to, as
    [{slug, name}, ...] ordered by display_order. 0..N — most tickers
    belong to no theme."""
    rows = db.execute(sql_text("""
        SELECT t.slug, t.name
        FROM theme_tickers tt
        JOIN themes t ON t.id = tt.theme_id
        WHERE tt.ticker = :ticker AND t.is_active
        ORDER BY t.display_order, t.name
    """), {"ticker": ticker}).fetchall()
    return [{"slug": r[0], "name": r[1]} for r in rows]


def theme_ticker_filter_sql(alias: str = "p", slug_param: str = "theme_slug") -> str:
    """Return an ``AND``-prefixed WHERE fragment restricting
    ``<alias>.ticker`` to a theme's members. The slug stays a bound
    parameter — callers must put the slug into their params dict under
    ``slug_param``."""
    prefix = f"{alias}." if alias else ""
    return (
        f" AND {prefix}ticker IN ("
        f"SELECT tt.ticker FROM theme_tickers tt "
        f"JOIN themes t ON t.id = tt.theme_id "
        f"WHERE t.slug = :{slug_param} AND t.is_active)"
    )
