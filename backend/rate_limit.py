from slowapi import Limiter
from slowapi.util import get_remote_address


def client_ip_key(request):
    """Rate-limit key = the real client IP.

    Railway runs the app behind a proxy and uvicorn is started WITHOUT
    --proxy-headers, so request.client.host is the proxy's IP, not the
    caller's. That makes get_remote_address() collapse every visitor into a
    single shared bucket — so a per-IP limit becomes a global limit. Read the
    real client from X-Forwarded-For (leftmost entry = original client as seen
    by the edge) and fall back to get_remote_address() when the header is
    absent (e.g. local dev) or malformed.
    """
    try:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first
    except Exception:
        pass
    return get_remote_address(request)


limiter = Limiter(key_func=client_ip_key)
