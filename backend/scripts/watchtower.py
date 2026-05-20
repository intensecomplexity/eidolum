#!/usr/bin/env python3
"""Auth-aware watchtower for the single cc_recover worker A.

B is retired (its pending work was merged into A's checkpoint). This tower
tracks A only. Detects deaths and 90-min stalls; relaunches up to
RESTART_BUDGET (5) times per rolling 24h.

Auth-aware: if run_cc_recovery.sh exits with code 42 (Railway CLI auth/link
probe failed — the patched fail-fast signal), the restart does NOT count
against the budget. Instead we enter an auth-wait state: probe
`railway variables -s Postgres -e production --json` every hour; relaunch
when the probe succeeds (user re-authed/re-linked). After 6 consecutive
failing probes we escalate LOUDLY (incident + stderr).

Suspend-aware: stall is measured with time.monotonic(), which on Linux does
not advance during suspend, so a laptop sleep doesn't accumulate fake stall
time.

Heartbeat every 5min to backend/scripts/_artifacts/watchtower.log (survives
the CC window closing).
"""
import argparse
import os
import json
import subprocess
import sys
import time
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/nimroddd/quantanalytics")
ART = ROOT / "backend/scripts/_artifacts"
LOG = ART / "watchtower.log"
INC = ART / "watchdog_incidents.log"
LAUNCH = ROOT / "backend/scripts/run_cc_recovery.sh"

HB_SEC = 300
STALL_MIN = 90
RESTART_BUDGET = 5
BUDGET_WINDOW = 24 * 3600
AUTH_RETRY_SEC = 3600          # probe railway every 1h while auth-dead
AUTH_ESCALATE_AFTER = 6        # 6 failing probes (≈6h) → LOUD escalate
EXIT_AUTH_DEAD = 42


def utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_line(path, msg):
    with open(path, "a") as f:
        f.write(f"[{utc()}] {msg}\n")


def log(msg):
    write_line(LOG, msg)


def incident(msg):
    write_line(INC, msg)
    write_line(LOG, f"INCIDENT: {msg}")


def loud(msg):
    """Write to stderr too — survives if anyone is tailing."""
    incident(f"LOUD: {msg}")
    sys.stderr.write(f"[{utc()}] WATCHTOWER LOUD: {msg}\n")
    sys.stderr.flush()


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def find_python_pid(suffix="_a"):
    try:
        r = subprocess.run(
            ["pgrep", "-af", "cc_recover_classifier_errors.py"],
            capture_output=True, text=True, timeout=5,
        )
        for line in r.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            pid, cmd = parts
            if cmd.startswith("python3") and f"_recovery_checkpoint{suffix}.json" in cmd:
                return int(pid)
    except Exception:
        pass
    return None


def ckpt_stats(path):
    try:
        d = json.loads(Path(path).read_text())
        c = Counter(v["status"] for v in d["videos"])
        preds = sum(
            v.get("result", {}).get("inserted", 0)
            for v in d["videos"] if v.get("result")
        )
        return c.get("done", 0), c.get("pending", 0), preds
    except Exception:
        return None, None, None


def kill_worker_tree(suffix="_a", hard_timeout=30):
    pattern = f"cc_recover_classifier_errors.py.*_recovery_checkpoint{suffix}.json"
    subprocess.run(["pkill", "-TERM", "-f", pattern], capture_output=True)
    waited = 0
    while waited < hard_timeout:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        if not r.stdout.strip():
            return True
        time.sleep(2)
        waited += 2
    subprocess.run(["pkill", "-KILL", "-f", pattern], capture_output=True)
    time.sleep(3)
    r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    return not r.stdout.strip()


def launch_worker(ckpt_path):
    """Invoke run_cc_recovery.sh. Returns (rc, new_pid_or_None)."""
    r = subprocess.run(
        ["bash", str(LAUNCH), "--checkpoint-path", str(ckpt_path)],
        capture_output=True, text=True, timeout=90, cwd=str(ROOT),
    )
    log(f"LAUNCH: rc={r.returncode} stdout={r.stdout.strip()!r}")
    if r.stderr.strip():
        log(f"LAUNCH: stderr={r.stderr.strip()!r}")
    if r.returncode == EXIT_AUTH_DEAD:
        return r.returncode, None
    if r.returncode != 0:
        return r.returncode, None
    for _ in range(20):
        time.sleep(2)
        new = find_python_pid("_a")
        if new:
            return r.returncode, new
    return r.returncode, None


def auth_probe_ok():
    """Direct check that railway CLI auth+link will let the worker launch."""
    try:
        r = subprocess.run(
            ["railway", "variables", "-s", "Postgres", "-e", "production", "--json"],
            capture_output=True, text=True, timeout=20, cwd=str(ROOT),
        )
        return r.returncode == 0
    except Exception:
        return False


def heartbeat(state):
    d, p, preds = ckpt_stats(state["ckpt_A"])
    mono = time.monotonic()
    if d is not None and state["last_done"] is not None and d > state["last_done"]:
        state["last_advance_mono"] = mono
        state["last_done"] = d
    stall = (mono - state["last_advance_mono"]) / 60
    cutoff = time.time() - BUDGET_WINDOW
    while state["restart_events"] and state["restart_events"][0] < cutoff:
        state["restart_events"].popleft()
    used = len(state["restart_events"])
    auth_status = "ok" if state["auth_status"] == "ok" else (
        f"dead_since={datetime.fromtimestamp(state['auth_dead_since'], tz=timezone.utc).strftime('%H:%MZ')}"
    )
    log(f"A: pid={state['pid_A']} done={d} pending={p} preds={preds} stall={stall:.1f}min")
    log(f"restarts_24h={used}/{RESTART_BUDGET} auth_status={auth_status}")


def try_restart(state):
    """Attempt to restart worker A. Handles exit-42 by entering auth-wait."""
    cutoff = time.time() - BUDGET_WINDOW
    while state["restart_events"] and state["restart_events"][0] < cutoff:
        state["restart_events"].popleft()
    if len(state["restart_events"]) >= RESTART_BUDGET:
        incident(
            f"BUDGET-EXHAUSTED: skipping restart "
            f"({len(state['restart_events'])}/{RESTART_BUDGET} in 24h)"
        )
        return False

    kill_worker_tree("_a")
    rc, new = launch_worker(state["ckpt_A"])

    if rc == EXIT_AUTH_DEAD:
        if state["auth_status"] == "ok":
            state["auth_status"] = "dead"
            state["auth_dead_since"] = time.time()
            state["auth_fail_count"] = 0
            state["last_auth_probe_mono"] = time.monotonic()
            incident("AUTH_DEAD: run_cc_recovery.sh exited 42; entering auth-wait (no budget hit)")
        return False

    if new:
        state["pid_A"] = new
        state["last_advance_mono"] = time.monotonic()
        state["last_done"] = ckpt_stats(state["ckpt_A"])[0]
        state["restart_events"].append(time.time())
        incident(
            f"RESTART_SUCCESS new_pid={new} "
            f"restarts_24h={len(state['restart_events'])}/{RESTART_BUDGET}"
        )
        return True

    incident(f"RESTART_FAILED rc={rc}: launch script ran but no python pid appeared")
    return False


def handle_auth_wait(state):
    """Called while auth_status=='dead'. Probes hourly; relaunches on success."""
    mono = time.monotonic()
    if mono - state["last_auth_probe_mono"] < AUTH_RETRY_SEC:
        return
    state["last_auth_probe_mono"] = mono
    if auth_probe_ok():
        log("AUTH_PROBE: ok — exiting auth-wait, attempting relaunch")
        state["auth_status"] = "ok"
        state["auth_dead_since"] = None
        state["auth_fail_count"] = 0
        rc, new = launch_worker(state["ckpt_A"])
        if rc == EXIT_AUTH_DEAD:
            # Race: probe passed but launch raced. Treat as still dead.
            state["auth_status"] = "dead"
            state["auth_dead_since"] = time.time()
            incident("AUTH_DEAD: probe ok but launch returned 42 (race)")
            return
        if new:
            state["pid_A"] = new
            state["last_advance_mono"] = time.monotonic()
            state["last_done"] = ckpt_stats(state["ckpt_A"])[0]
            state["restart_events"].append(time.time())
            incident(
                f"AUTH_RESTORED: relaunched pid={new} "
                f"restarts_24h={len(state['restart_events'])}/{RESTART_BUDGET}"
            )
        else:
            incident(f"AUTH_RESTORED: probe ok but no pid appeared, rc={rc}")
        return

    state["auth_fail_count"] += 1
    log(f"AUTH_PROBE: still failing ({state['auth_fail_count']}/{AUTH_ESCALATE_AFTER})")
    if state["auth_fail_count"] >= AUTH_ESCALATE_AFTER and not state["escalated"]:
        loud(
            f"AUTH still dead after {state['auth_fail_count']}h. "
            f"Recovery is FROZEN. Run 'railway login' && 'railway link -p secure-insight -e production' "
            f"on host {os.uname().nodename}."
        )
        state["escalated"] = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid-a", type=int, required=True)
    args = ap.parse_args()

    ckpt_A = ART / "_recovery_checkpoint_a.json"
    d0, p0, preds0 = ckpt_stats(ckpt_A)
    start_mono = time.monotonic()
    state = {
        "pid_A": args.pid_a,
        "ckpt_A": ckpt_A,
        "last_done": d0,
        "last_advance_mono": start_mono,
        "restart_events": deque(),
        "start_mono": start_mono,
        "auth_status": "ok",
        "auth_dead_since": None,
        "auth_fail_count": 0,
        "last_auth_probe_mono": start_mono,
        "escalated": False,
    }

    log(f"=== WATCHTOWER START (single-worker A, auth-aware) === pid_A={args.pid_a}; "
        f"A_done={d0} A_pending={p0} A_preds={preds0}")
    heartbeat(state)

    last_hb_mono = time.monotonic()
    second_hb_emitted = False

    while True:
        time.sleep(60)
        mono = time.monotonic()

        if state["auth_status"] != "ok":
            handle_auth_wait(state)
        else:
            pid = state["pid_A"]
            d, _, _ = ckpt_stats(state["ckpt_A"])
            if d is not None and state["last_done"] is not None and d > state["last_done"]:
                state["last_advance_mono"] = mono
                state["last_done"] = d
            stall = (mono - state["last_advance_mono"]) / 60
            if not pid_alive(pid):
                incident(f"TRIGGER: python pid {pid} DEAD")
                try_restart(state)
            elif stall >= STALL_MIN:
                incident(f"TRIGGER: stall {stall:.1f}min ≥ {STALL_MIN}min")
                try_restart(state)

        if not second_hb_emitted and mono - state["start_mono"] >= 60:
            heartbeat(state)
            last_hb_mono = mono
            second_hb_emitted = True
        elif mono - last_hb_mono >= HB_SEC:
            heartbeat(state)
            last_hb_mono = mono


if __name__ == "__main__":
    main()
