"""
KeyScrubFilter — defense-in-depth scrubbing of API keys from log output.

Why this exists:
  httpx and urllib3 log full request URLs at INFO level. Any vendor that
  authenticates via a query string (FMP /stable/ endpoints, Tiingo,
  Finnhub, Alpha Vantage, etc.) leaks its key into Railway logs unless
  the URL is rewritten before the log line is emitted.

Strategy:
  Massive and Apify already use header auth (see fix(security) commits),
  so the call sites no longer attach keys to the URL. FMP only supports
  ?apikey=<key> on the /stable/ namespace, so its calls still leak by
  construction. This filter rewrites the leaked segments at the logging
  layer as a belt-and-suspenders backstop — if a future call site
  regresses to query-string auth, the filter still keeps the key out
  of the logs.

Install once at process startup BEFORE any HTTP client logger has had
its first record formatted, by calling install_key_scrubber().
"""
import logging
import re

# Match common query-string forms across vendors:
#   apikey=, apiKey=, api_key=, token=
# The terminator is &, whitespace, end-of-string, or a quote. We also
# exclude `<` so the substitution result `apikey=<REDACTED>` does NOT
# itself match a second time when the filter is applied twice (which
# happens when a child logger like httpx propagates to root and both
# loggers carry the filter).
_KEY_SCRUB_RE = re.compile(
    r'(?i)(apikey|api_key|token)=[^&\s"\'<>]+',
)


def _scrub(text: str) -> str:
    return _KEY_SCRUB_RE.sub(lambda m: f"{m.group(1)}=<REDACTED>", text)


def _scrub_arg(arg):
    """Scrub a single log arg.

    httpx logs the URL as a `httpx.URL` object, not a string — the URL
    only becomes a string when the handler does `msg % args`. So we
    can't filter by `isinstance(arg, str)`; we have to stringify first
    and replace the arg with the scrubbed string when it actually
    contains a key. Replacing the arg is safe because `%s` formatting
    already calls `str()` on the value.
    """
    if isinstance(arg, str):
        return _scrub(arg) if "=" in arg else arg
    try:
        s = str(arg)
    except Exception:
        return arg
    if "=" not in s:
        return arg
    scrubbed = _scrub(s)
    return scrubbed if scrubbed != s else arg


class KeyScrubFilter(logging.Filter):
    """Strip API keys from log records before they're emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str) and "=" in record.msg:
                record.msg = _scrub(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: _scrub_arg(v) for k, v in record.args.items()}
                else:
                    record.args = tuple(_scrub_arg(a) for a in record.args)
        except Exception:
            # Never let scrubbing kill a log line — the record is more
            # valuable than perfect scrubbing.
            pass
        return True


def install_key_scrubber() -> None:
    """Attach KeyScrubFilter to the loggers most likely to emit URLs.

    Idempotent: re-installing is a no-op (filters compare by identity, so
    add the same instance every time and it only sticks once per logger).
    """
    f = KeyScrubFilter()
    for name in (
        "",  # root — catches anything not handled by a more specific logger
        "httpx",
        "httpcore",
        "httpcore.http11",
        "httpcore.connection",
        "urllib3",
        "urllib3.connectionpool",
        "requests",
    ):
        logger = logging.getLogger(name)
        if not any(isinstance(existing, KeyScrubFilter) for existing in logger.filters):
            logger.addFilter(f)
        # Also attach to any handlers already present so the filter runs
        # before formatting (filter on the logger only fires for records
        # propagated through that logger; handler-level filters fire on
        # whatever the handler sees, including child-logger output).
        for handler in logger.handlers:
            if not any(isinstance(existing, KeyScrubFilter) for existing in handler.filters):
                handler.addFilter(f)
