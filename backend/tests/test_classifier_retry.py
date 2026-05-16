"""Unit test for call_runpod_vllm retry-with-backoff (classifier hardening).

Mocks the streaming HTTP call to fail with HTTP 524 twice, then succeed,
and asserts the retry loop kicks in with the 5s / 15s backoff and returns
the eventual success content.

Run:  python3 tests/test_classifier_retry.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Config the classifier code reads at import / call time. Dummy values —
# the HTTP layer is fully mocked, nothing real is contacted.
os.environ.setdefault("CLASSIFIER_BASE_URL", "https://dummy.invalid")
os.environ.setdefault("CF_ACCESS_CLIENT_ID", "dummy-id")
os.environ.setdefault("CF_ACCESS_CLIENT_SECRET", "dummy-secret")


class _FakeStreamResp:
    """Stands in for an httpx streaming Response used as a context manager."""
    def __init__(self, status_code, sse_lines=None, body=b"gateway error"):
        self.status_code = status_code
        self._sse = sse_lines or []
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body

    def iter_lines(self):
        return iter(self._sse)


def main():
    import httpx
    import jobs.youtube_classifier as clf

    # success SSE: one content delta then [DONE]
    ok_lines = [
        'data: {"choices":[{"delta":{"content":"[]"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":2}}',
        "data: [DONE]",
    ]
    calls = {"n": 0}

    def fake_stream(method, url, **kw):
        calls["n"] += 1
        if calls["n"] <= 2:
            return _FakeStreamResp(524)          # transient — must retry
        return _FakeStreamResp(200, sse_lines=ok_lines)

    sleeps = []
    orig_stream, orig_sleep = httpx.stream, clf.time.sleep
    httpx.stream = fake_stream
    clf.time.sleep = lambda s: sleeps.append(s)
    try:
        content, cost, latency = clf.call_runpod_vllm(
            "Some transcript about Apple stock going up.",
            "TestChannel", "Test Title", "2026-01-01", "vid123",
        )
    finally:
        httpx.stream, clf.time.sleep = orig_stream, orig_sleep

    failures = []
    if calls["n"] != 3:
        failures.append(f"expected 3 HTTP attempts (2 fail + 1 ok), got {calls['n']}")
    if sleeps != [5, 15]:
        failures.append(f"expected backoff [5, 15], got {sleeps}")
    if sum(sleeps) != 20:
        failures.append(f"expected total backoff 20s, got {sum(sleeps)}s")
    if content != "[]":
        failures.append(f"expected success content '[]', got {content!r}")

    # terminal error (HTTP 403) must NOT retry
    calls["n"] = 0
    sleeps.clear()
    httpx.stream = lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1)
                                    or _FakeStreamResp(403))
    clf.time.sleep = lambda s: sleeps.append(s)
    try:
        clf.call_runpod_vllm("t", "c", "t", "2026-01-01", "v")
        failures.append("HTTP 403 should have raised, did not")
    except RuntimeError:
        if calls["n"] != 1:
            failures.append(f"403 must not retry — expected 1 attempt, got {calls['n']}")
        if sleeps:
            failures.append(f"403 must not back off, slept {sleeps}")
    except Exception as e:
        failures.append(f"403 raised {type(e).__name__}, expected RuntimeError")
    finally:
        httpx.stream, clf.time.sleep = orig_stream, orig_sleep

    if failures:
        print("FAIL:")
        for f in failures:
            print("  -", f)
        return 1
    print("PASS: 524×2→200 retried with backoff [5,15] (20s total); "
          "HTTP 403 failed fast with no retry.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
