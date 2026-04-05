"""Serve processed ticker logos from the database with aggressive caching."""
import time as _time
from collections import OrderedDict
from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import text as sql_text
from database import SessionLocal

router = APIRouter()

# ── In-memory LRU cache ──────────────────────────────────────────────────────
_MAX_CACHE = 500
_cache: OrderedDict[str, tuple[bytes, float]] = OrderedDict()
_CACHE_TTL = 3600  # 1 hour in-memory


def _get_cached(ticker: str) -> bytes | None:
    entry = _cache.get(ticker)
    if entry and (_time.time() - entry[1]) < _CACHE_TTL:
        _cache.move_to_end(ticker)
        return entry[0]
    return None


def _set_cached(ticker: str, data: bytes):
    _cache[ticker] = (data, _time.time())
    if len(_cache) > _MAX_CACHE:
        _cache.popitem(last=False)


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.get("/logo/{ticker}.png")
async def serve_logo(ticker: str, request: Request):
    """Serve a processed logo PNG. Returns 404 if not yet processed."""
    ticker = ticker.upper().replace(".PNG", "")

    # Check memory cache
    cached = _get_cached(ticker)
    if cached:
        return Response(
            content=cached,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=604800", "X-Logo-Source": "cache"},
        )

    # Check DB
    db = SessionLocal()
    try:
        row = db.execute(sql_text(
            "SELECT image_data FROM processed_logos WHERE ticker = :t"
        ), {"t": ticker}).first()
    finally:
        db.close()

    if not row or not row[0]:
        return Response(status_code=404, content="", media_type="text/plain")

    image_data = bytes(row[0])
    _set_cached(ticker, image_data)

    return Response(
        content=image_data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=604800", "X-Logo-Source": "db"},
    )
