"""One-shot status probe for grounding_wide_window_sweep.

Prints a single-line status once every 30s for 5 minutes (10 iterations)
then exits.

Output line format (one per iteration):
    [HH:MM:SS] alive=Y log_age=14s current=150/1877 vid=abc12345 net_conns=3 5min_rate=5.8/min

    alive        Y/N from os.kill(pid, 0)
    log_age      seconds since the log file was last written
    current      most-recent "[i/total] vid=..." marker in the log
    net_conns    count of ESTABLISHED TCP sockets owned by the process
                 (from `ss -tnp | grep pid=<PID>,`)
    5min_rate    unique video_ids processed in the last 300s, /min

Usage:
    python3 backend/scripts/sweep_status_probe.py [LOG] [PID]

If PID is omitted, auto-finds via `pgrep -f grounding_wide_window_sweep`.
"""
from __future__ import annotations

import datetime
import os
import re
import subprocess
import sys
import time

DEFAULT_LOG = "/tmp/sweep_full2.log"
ITERATIONS = 10
INTERVAL_SEC = 30
RATE_WINDOW_SEC = 300

# Matches the sweep's per-video progress line:
#   [YT-TS...] [HH:MM:SS] [i/total] vid=<video_id> preds=<N>
VID_RE = re.compile(
    r"\[(\d{2}:\d{2}:\d{2})\]\s+\[(\d+)/(\d+)\]\s+vid=(\S+)"
)


def auto_pid() -> int | None:
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "grounding_wide_window_sweep"],
            text=True,
        ).strip().splitlines()
        # Filter out our own probe PID.
        my = os.getpid()
        for line in out:
            pid = int(line)
            if pid != my:
                return pid
    except Exception:
        pass
    return None


def is_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def net_conns(pid: int | None) -> int:
    if not pid:
        return 0
    try:
        out = subprocess.check_output(
            ["ss", "-tnp"],
            text=True, stderr=subprocess.DEVNULL,
        )
    except Exception:
        return 0
    needle = f"pid={pid},"
    return sum(1 for line in out.splitlines() if needle in line)


def log_age(path: str) -> int:
    try:
        return int(time.time() - os.path.getmtime(path))
    except Exception:
        return -1


def scan(path: str, window_sec: int = RATE_WINDOW_SEC) -> tuple[str, float]:
    """Return (current_marker, rate_per_min).

    current_marker: latest "i/total vid=<id>" from the log.
    rate_per_min:   unique video_ids whose HH:MM:SS is within the
                    last `window_sec` seconds, divided by minutes.
    """
    now = datetime.datetime.now()
    cutoff = now - datetime.timedelta(seconds=window_sec)
    vids_in_window: set[str] = set()
    last_marker = "-"
    try:
        with open(path) as f:
            for line in f:
                m = VID_RE.search(line)
                if not m:
                    continue
                hhmmss, cur, tot, vid = m.groups()
                last_marker = f"{cur}/{tot} vid={vid[:11]}"
                try:
                    hh, mm, ss = (int(x) for x in hhmmss.split(":"))
                    t = now.replace(hour=hh, minute=mm, second=ss, microsecond=0)
                    # Midnight rollover: if the log timestamp is more
                    # than 2h in the "future" relative to now, treat it
                    # as yesterday.
                    if (t - now).total_seconds() > 7200:
                        t -= datetime.timedelta(days=1)
                    if t >= cutoff:
                        vids_in_window.add(vid)
                except Exception:
                    pass
    except FileNotFoundError:
        return ("log-missing", 0.0)
    except Exception:
        return (last_marker, 0.0)
    rate = len(vids_in_window) / (window_sec / 60.0)
    return last_marker, rate


def main():
    log_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LOG
    pid: int | None = int(sys.argv[2]) if len(sys.argv) > 2 else auto_pid()

    banner = (f"sweep_status_probe — log={log_path} pid={pid} "
              f"({ITERATIONS} iterations × {INTERVAL_SEC}s)")
    print(banner, flush=True)

    for i in range(ITERATIONS):
        ts = time.strftime("%H:%M:%S")
        alive = is_alive(pid)
        age = log_age(log_path)
        current, rate = scan(log_path)
        nc = net_conns(pid) if alive else 0
        alive_tag = "Y" if alive else "N"
        stuck = "STUCK" if alive and age > 120 else "ok"
        print(
            f"[{ts}] alive={alive_tag} log_age={age}s "
            f"current={current} net_conns={nc} "
            f"5min_rate={rate:.1f}/min [{stuck}]",
            flush=True,
        )
        if i < ITERATIONS - 1:
            time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
