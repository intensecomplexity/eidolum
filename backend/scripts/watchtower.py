#!/usr/bin/env python3
"""Dual-worker watchtower (A + B) with REPORT-ONLY 4-hour measurement gate.

Tracks both cc_recover worker pids, each with its own 90-min stall counter.
Auto-restarts up to RESTART_BUDGET (5) times per rolling 24h, COMBINED
across A and B.

Auth-aware: if run_cc_recovery.sh exits with EXIT_AUTH_DEAD (42 — the
patched Railway-CLI probe failure signal), the restart does NOT count
against budget. Instead we enter auth-wait: hourly
`railway variables -s Postgres -e production --json` probe; relaunch any
missing worker when the probe succeeds. After AUTH_ESCALATE_AFTER (6)
consecutive failing probes (~6h) we escalate LOUDLY (incident + stderr).

Suspend-aware: stall is measured with time.monotonic() (Linux
CLOCK_MONOTONIC, which does NOT advance during system suspend, so a
laptop sleep doesn't accumulate fake stall time). As a sanity backstop,
each tick we also compare wall-clock delta against the expected sleep
interval — a large gap is logged as a SUSPEND event for visibility.

GATE_AT_SEC (4h after launch) computes the combined videos/hr rate and
writes a single 4H_GATE_REPORT line with a verdict
(keep_clear_win / keep_marginal_win / consider_consolidate). Verdict is
REPORT-ONLY — the watchtower never auto-consolidates. The human decides.

Heartbeat persists to backend/scripts/_artifacts/watchtower.log so it
survives the CC window closing.
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
TICK_SEC = 60
STALL_MIN = 90
RESTART_BUDGET = 5         # combined A+B per 24h
BUDGET_WINDOW = 24 * 3600
AUTH_RETRY_SEC = 3600       # hourly probe while auth-dead
AUTH_ESCALATE_AFTER = 6     # 6 failing probes (~6h) → LOUD
EXIT_AUTH_DEAD = 42
GATE_AT_SEC = 4 * 3600      # 4h report-only measurement gate
GATE_BASELINE = 29          # parallel-baseline (single-worker proxy: ingest 29/hr)
SUSPEND_DETECT_SEC = TICK_SEC + 60  # wall delta beyond this = likely suspend


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


def find_python_pid(suffix):
    """suffix = '_a' or '_b'. Returns the python3 worker pid (not railway wrapper)."""
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


def kill_worker_tree(suffix, hard_timeout=30):
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


def launch_worker(ckpt_path, suffix):
    """Invoke run_cc_recovery.sh. Returns (rc, new_pid_or_None).
    rc == EXIT_AUTH_DEAD signals Railway auth/link probe failure."""
    r = subprocess.run(
        ["bash", str(LAUNCH), "--checkpoint-path", str(ckpt_path)],
        capture_output=True, text=True, timeout=90, cwd=str(ROOT),
    )
    log(f"LAUNCH {suffix}: rc={r.returncode} stdout={r.stdout.strip()!r}")
    if r.stderr.strip():
        log(f"LAUNCH {suffix}: stderr={r.stderr.strip()!r}")
    if r.returncode == EXIT_AUTH_DEAD:
        return r.returncode, None
    if r.returncode != 0:
        return r.returncode, None
    for _ in range(20):
        time.sleep(2)
        new = find_python_pid(suffix)
        if new:
            return r.returncode, new
    return r.returncode, None


def auth_probe_ok():
    try:
        r = subprocess.run(
            ["railway", "variables", "-s", "Postgres", "-e", "production", "--json"],
            capture_output=True, text=True, timeout=20, cwd=str(ROOT),
        )
        return r.returncode == 0
    except Exception:
        return False


def heartbeat(state):
    mono = time.monotonic()
    rows = {}
    for label in ("A", "B"):
        d, p, preds = ckpt_stats(state[f"ckpt_{label}"])
        if d is not None and state["last_done"][label] is not None and d > state["last_done"][label]:
            state["last_advance_mono"][label] = mono
            state["last_done"][label] = d
        stall = (mono - state["last_advance_mono"][label]) / 60
        rows[label] = (d, p, preds, stall)

    cutoff = time.time() - BUDGET_WINDOW
    while state["restart_events"] and state["restart_events"][0][0] < cutoff:
        state["restart_events"].popleft()
    used = len(state["restart_events"])

    if state["auth_status"] == "ok":
        auth_status = "ok"
    else:
        auth_status = f"dead_for_{int((time.time() - state['auth_dead_since'])/60)}min"

    for label in ("A", "B"):
        d, p, preds, stall = rows[label]
        log(f"{label}: pid={state[f'pid_{label}']} done={d} pending={p} preds={preds} stall={stall:.1f}min")
    done_total = (rows["A"][0] or 0) + (rows["B"][0] or 0)
    preds_total = (rows["A"][2] or 0) + (rows["B"][2] or 0)
    log(f"COMBINED: done_total={done_total} preds_total={preds_total} "
        f"restarts_24h={used}/{RESTART_BUDGET} auth_status={auth_status}")


def try_restart(state, label, suffix):
    """Attempt restart of worker `label` ('A' or 'B'). Honors combined budget;
    on EXIT_AUTH_DEAD, drops into auth-wait without consuming budget."""
    cutoff = time.time() - BUDGET_WINDOW
    while state["restart_events"] and state["restart_events"][0][0] < cutoff:
        state["restart_events"].popleft()
    if len(state["restart_events"]) >= RESTART_BUDGET:
        incident(
            f"BUDGET-EXHAUSTED {label}: skipping restart "
            f"({len(state['restart_events'])}/{RESTART_BUDGET} in 24h, combined)"
        )
        return False

    kill_worker_tree(suffix)
    rc, new = launch_worker(state[f"ckpt_{label}"], suffix)

    if rc == EXIT_AUTH_DEAD:
        if state["auth_status"] == "ok":
            state["auth_status"] = "dead"
            state["auth_dead_since"] = time.time()
            state["auth_fail_count"] = 0
            state["last_auth_probe_mono"] = time.monotonic()
            incident(f"AUTH_DEAD ({label}): launch returned 42; entering auth-wait (no budget hit)")
        state[f"pid_{label}"] = None
        return False

    if new:
        state[f"pid_{label}"] = new
        state["last_advance_mono"][label] = time.monotonic()
        state["last_done"][label] = ckpt_stats(state[f"ckpt_{label}"])[0]
        state["restart_events"].append((time.time(), label))
        incident(
            f"RESTART_SUCCESS {label} new_pid={new} "
            f"restarts_24h={len(state['restart_events'])}/{RESTART_BUDGET}"
        )
        return True

    incident(f"RESTART_FAILED {label} rc={rc}: launch ran but no python pid appeared")
    return False


def handle_auth_wait(state):
    """Hourly Railway probe while auth_status=='dead'. Relaunch any dead worker on success.
    LOUD escalate after AUTH_ESCALATE_AFTER consecutive failures."""
    mono = time.monotonic()
    if mono - state["last_auth_probe_mono"] < AUTH_RETRY_SEC:
        return
    state["last_auth_probe_mono"] = mono

    if not auth_probe_ok():
        state["auth_fail_count"] += 1
        log(f"AUTH_PROBE: still failing ({state['auth_fail_count']}/{AUTH_ESCALATE_AFTER})")
        if state["auth_fail_count"] >= AUTH_ESCALATE_AFTER and not state["escalated"]:
            loud(
                f"AUTH still dead after {state['auth_fail_count']}h. Recovery FROZEN. "
                f"Run 'railway login' && 'railway link -p secure-insight -e production' "
                f"on host {os.uname().nodename}."
            )
            state["escalated"] = True
        return

    log("AUTH_PROBE: ok — exiting auth-wait, relaunching any dead workers")
    state["auth_status"] = "ok"
    state["auth_dead_since"] = None
    state["auth_fail_count"] = 0
    state["escalated"] = False
    for label, suffix in (("A", "_a"), ("B", "_b")):
        if not pid_alive(state[f"pid_{label}"]):
            rc, new = launch_worker(state[f"ckpt_{label}"], suffix)
            if rc == EXIT_AUTH_DEAD:
                state["auth_status"] = "dead"
                state["auth_dead_since"] = time.time()
                incident(f"AUTH_DEAD ({label}): probe ok but relaunch returned 42 (race)")
                return
            if new:
                state[f"pid_{label}"] = new
                state["last_advance_mono"][label] = time.monotonic()
                state["last_done"][label] = ckpt_stats(state[f"ckpt_{label}"])[0]
                state["restart_events"].append((time.time(), label))
                incident(
                    f"AUTH_RESTORED {label}: relaunched pid={new} "
                    f"restarts_24h={len(state['restart_events'])}/{RESTART_BUDGET}"
                )
            else:
                incident(f"AUTH_RESTORED {label}: probe ok but no pid appeared, rc={rc}")


def evaluate_gate(state):
    """4-hour report-only gate. Computes combined videos/hr rate and verdict.
    Never auto-acts."""
    mono = time.monotonic()
    elapsed_hr = (mono - state["start_mono"]) / 3600
    dA, _, prA = ckpt_stats(state["ckpt_A"])
    dB, _, prB = ckpt_stats(state["ckpt_B"])
    gained_done = ((dA or 0) - state["done_at_arm"]["A"]) + ((dB or 0) - state["done_at_arm"]["B"])
    gained_preds = ((prA or 0) - state["preds_at_arm"]["A"]) + ((prB or 0) - state["preds_at_arm"]["B"])
    rate = gained_done / elapsed_hr if elapsed_hr > 0 else 0

    if rate >= 40:
        verdict = "keep_clear_win"
    elif rate >= 30:
        verdict = "keep_marginal_win"
    else:
        verdict = "consider_consolidate"

    log(f"4H_GATE_REPORT: combined_rate={rate:.1f}/hr "
        f"parallel_baseline={GATE_BASELINE}/hr verdict={verdict} "
        f"(elapsed_hr={elapsed_hr:.2f} gained_done={gained_done} gained_preds={gained_preds}) "
        f"[REPORT-ONLY, no auto-action]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid-a", type=int, required=True)
    ap.add_argument("--pid-b", type=int, required=True)
    args = ap.parse_args()

    ckpt_A = ART / "_recovery_checkpoint_a.json"
    ckpt_B = ART / "_recovery_checkpoint_b.json"

    dA0, pA0, prA0 = ckpt_stats(ckpt_A)
    dB0, pB0, prB0 = ckpt_stats(ckpt_B)
    start_mono = time.monotonic()
    start_wall = time.time()

    state = {
        "pid_A": args.pid_a, "pid_B": args.pid_b,
        "ckpt_A": ckpt_A, "ckpt_B": ckpt_B,
        "last_done": {"A": dA0, "B": dB0},
        "last_advance_mono": {"A": start_mono, "B": start_mono},
        "done_at_arm": {"A": dA0 or 0, "B": dB0 or 0},
        "preds_at_arm": {"A": prA0 or 0, "B": prB0 or 0},
        "restart_events": deque(),
        "start_mono": start_mono,
        "auth_status": "ok",
        "auth_dead_since": None,
        "auth_fail_count": 0,
        "last_auth_probe_mono": start_mono,
        "escalated": False,
        "gate_reported": False,
    }

    log(
        f"=== WATCHTOWER START (dual A+B, 4h REPORT-ONLY gate) === "
        f"pid_A={args.pid_a} pid_B={args.pid_b}; "
        f"A_done={dA0} A_pending={pA0} A_preds={prA0}; "
        f"B_done={dB0} B_pending={pB0} B_preds={prB0}; "
        f"gate_at=4h baseline={GATE_BASELINE}/hr verdict_thresholds=[<30,30-39,≥40]"
    )
    heartbeat(state)

    last_hb_mono = start_mono
    last_wall = start_wall
    second_hb_emitted = False

    while True:
        time.sleep(TICK_SEC)
        mono = time.monotonic()
        wall = time.time()

        # Suspend detection (sanity): wall delta should be ~TICK_SEC.
        # Larger gaps mean the system was suspended — log for visibility.
        wall_delta = wall - last_wall
        if wall_delta > SUSPEND_DETECT_SEC:
            log(f"SUSPEND_DETECTED: wall_delta={wall_delta:.0f}s ≫ tick={TICK_SEC}s "
                f"(monotonic stall counters paused naturally)")
        last_wall = wall

        if state["auth_status"] != "ok":
            handle_auth_wait(state)
        else:
            for label, suffix in (("A", "_a"), ("B", "_b")):
                pid = state[f"pid_{label}"]
                d, _, _ = ckpt_stats(state[f"ckpt_{label}"])
                if d is not None and state["last_done"][label] is not None and d > state["last_done"][label]:
                    state["last_advance_mono"][label] = mono
                    state["last_done"][label] = d
                stall = (mono - state["last_advance_mono"][label]) / 60
                if not pid_alive(pid):
                    incident(f"TRIGGER {label}: python pid {pid} DEAD")
                    try_restart(state, label, suffix)
                    if state["auth_status"] != "ok":
                        break  # don't try B in same tick after auth death
                elif stall >= STALL_MIN:
                    incident(f"TRIGGER {label}: stall {stall:.1f}min ≥ {STALL_MIN}min")
                    try_restart(state, label, suffix)
                    if state["auth_status"] != "ok":
                        break

        if (not state["gate_reported"]
                and mono - state["start_mono"] >= GATE_AT_SEC):
            evaluate_gate(state)
            state["gate_reported"] = True

        if not second_hb_emitted and mono - state["start_mono"] >= 60:
            heartbeat(state)
            last_hb_mono = mono
            second_hb_emitted = True
        elif mono - last_hb_mono >= HB_SEC:
            heartbeat(state)
            last_hb_mono = mono


if __name__ == "__main__":
    main()
