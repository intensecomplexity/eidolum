#!/usr/bin/env python3
"""Watchtower for cc_recover workers A and B.

Tracks both python pids and both checkpoints. Detects deaths and 90-min stalls,
relaunches up to RESTART_BUDGET (5) times per rolling 24h COMBINED. Suspend-aware:
stall is measured in monotonic time, which pauses during system suspend (so a
laptop sleep doesn't accumulate fake stall time).

After 2h from re-arm, evaluates combined preds/hr. If ≤24/hr, consolidates:
graceful stop both workers, merge B's pending video_ids into A's checkpoint,
relaunch A only. B retires.

Heartbeat every 5min to backend/scripts/_artifacts/watchtower.log.
Incidents to backend/scripts/_artifacts/watchdog_incidents.log.
"""
import argparse
import json
import os
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
CONSOLIDATE_AT_SEC = 2 * 3600
CONSOLIDATE_RATE = 24  # preds/hr combined threshold


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


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def find_python_pid(suffix):
    """suffix is '_a' or '_b'."""
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


def relaunch(label, ckpt_path, suffix):
    log(f"RELAUNCH {label}: invoking run_cc_recovery.sh")
    r = subprocess.run(
        ["bash", str(LAUNCH), "--checkpoint-path", str(ckpt_path)],
        capture_output=True, text=True, timeout=90, cwd=str(ROOT),
    )
    log(f"RELAUNCH {label}: rc={r.returncode} stdout={r.stdout.strip()!r}")
    if r.stderr.strip():
        log(f"RELAUNCH {label}: stderr={r.stderr.strip()!r}")
    for _ in range(20):
        time.sleep(2)
        new = find_python_pid(suffix)
        if new:
            return new
    return None


def consolidate(state):
    incident("CONSOLIDATE-DECISION: combined rate ≤24/hr after 2h — killing B, merging B→A")
    kill_worker_tree("_b")
    state["pid_B"] = None
    log("CONSOLIDATE: B tree killed")

    kill_worker_tree("_a", hard_timeout=120)
    state["pid_A"] = None
    log("CONSOLIDATE: A tree killed")

    a = json.loads(Path(state["ckpt_A"]).read_text())
    b = json.loads(Path(state["ckpt_B"]).read_text())
    backup_path = str(state["ckpt_A"]) + ".pre_consolidate"
    Path(backup_path).write_text(json.dumps(a))
    seen = {v["video_id"] for v in a["videos"]}
    added = 0
    for v in b["videos"]:
        if v.get("status") == "pending" and v["video_id"] not in seen:
            a["videos"].append({"video_id": v["video_id"], "status": "pending", "attempts": 0})
            added += 1
    a["updated_at"] = datetime.now(timezone.utc).isoformat()
    Path(state["ckpt_A"]).write_text(json.dumps(a))
    log(f"CONSOLIDATE: merged {added} B-pending videos into A; backup={backup_path}")

    new_pid = relaunch("A", state["ckpt_A"], "_a")
    if new_pid:
        state["pid_A"] = new_pid
        state["last_advance_mono"]["A"] = time.monotonic()
        state["last_done"]["A"] = ckpt_stats(state["ckpt_A"])[0]
        incident(f"CONSOLIDATE: A relaunched pid={new_pid}; B retired permanently")
    else:
        incident("CONSOLIDATE: A relaunch FAILED — manual intervention required")
    state["consolidated"] = True


def heartbeat(state):
    dA, pA, prA = ckpt_stats(state["ckpt_A"])
    dB, pB, prB = ckpt_stats(state["ckpt_B"])
    mono = time.monotonic()
    if dA is not None and state["last_done"]["A"] is not None and dA > state["last_done"]["A"]:
        state["last_advance_mono"]["A"] = mono
        state["last_done"]["A"] = dA
    if (state["pid_B"] and dB is not None and state["last_done"]["B"] is not None
            and dB > state["last_done"]["B"]):
        state["last_advance_mono"]["B"] = mono
        state["last_done"]["B"] = dB
    stallA = (mono - state["last_advance_mono"]["A"]) / 60
    stallB = (mono - state["last_advance_mono"]["B"]) / 60 if state["pid_B"] else 0
    cutoff = time.time() - BUDGET_WINDOW
    while state["restart_events"] and state["restart_events"][0][0] < cutoff:
        state["restart_events"].popleft()
    used = len(state["restart_events"])
    log(f"A: pid={state['pid_A']} done={dA} pending={pA} preds={prA} stall={stallA:.1f}min")
    if state["pid_B"]:
        log(f"B: pid={state['pid_B']} done={dB} pending={pB} preds={prB} stall={stallB:.1f}min")
    else:
        log("B: RETIRED (consolidated into A)")
    done_total = (dA or 0) + (dB or 0)
    preds_total = (prA or 0) + (prB or 0)
    log(f"COMBINED: done_total={done_total} preds_total={preds_total} restarts_24h={used}/{RESTART_BUDGET}")


def try_restart(state, label, suffix):
    cutoff = time.time() - BUDGET_WINDOW
    while state["restart_events"] and state["restart_events"][0][0] < cutoff:
        state["restart_events"].popleft()
    if len(state["restart_events"]) >= RESTART_BUDGET:
        incident(
            f"BUDGET-EXHAUSTED {label}: skipping restart "
            f"({len(state['restart_events'])}/{RESTART_BUDGET} in 24h)"
        )
        return False
    kill_worker_tree(suffix)
    new = relaunch(label, state[f"ckpt_{label}"], suffix)
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
    incident(f"RESTART_FAILED {label}: launch script ran but no python pid appeared")
    return False


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
    state = {
        "pid_A": args.pid_a, "pid_B": args.pid_b,
        "ckpt_A": ckpt_A, "ckpt_B": ckpt_B,
        "last_done": {"A": dA0, "B": dB0},
        "last_advance_mono": {"A": start_mono, "B": start_mono},
        "preds_at_arm": {"A": prA0 or 0, "B": prB0 or 0},
        "restart_events": deque(),
        "consolidated": False,
        "consolidate_evaluated": False,
        "start_mono": start_mono,
    }

    log(
        f"=== WATCHTOWER START === pid_A={args.pid_a} pid_B={args.pid_b}; "
        f"A_done={dA0} A_pending={pA0} A_preds={prA0}; "
        f"B_done={dB0} B_pending={pB0} B_preds={prB0}"
    )
    heartbeat(state)

    last_hb_mono = time.monotonic()
    second_hb_emitted = False

    while True:
        time.sleep(60)
        mono = time.monotonic()

        for label, suffix in (("A", "_a"), ("B", "_b")):
            pid = state[f"pid_{label}"]
            if pid is None:
                continue
            ckpt = state[f"ckpt_{label}"]
            d, _, _ = ckpt_stats(ckpt)
            if d is not None and state["last_done"][label] is not None and d > state["last_done"][label]:
                state["last_advance_mono"][label] = mono
                state["last_done"][label] = d
            stall = (mono - state["last_advance_mono"][label]) / 60
            if not pid_alive(pid):
                incident(f"TRIGGER {label}: python pid {pid} DEAD")
                try_restart(state, label, suffix)
                continue
            if stall >= STALL_MIN:
                incident(f"TRIGGER {label}: stall {stall:.1f}min ≥ {STALL_MIN}min")
                try_restart(state, label, suffix)
                continue

        if (not state["consolidate_evaluated"]
                and mono - state["start_mono"] >= CONSOLIDATE_AT_SEC
                and not state["consolidated"]):
            state["consolidate_evaluated"] = True
            elapsed_hr = (mono - state["start_mono"]) / 3600
            _, _, prA = ckpt_stats(ckpt_A)
            _, _, prB = ckpt_stats(ckpt_B)
            gainedA = (prA or 0) - state["preds_at_arm"]["A"]
            gainedB = (prB or 0) - state["preds_at_arm"]["B"]
            rate = (gainedA + gainedB) / elapsed_hr if elapsed_hr > 0 else 0
            log(
                f"CONSOLIDATE-EVAL: elapsed={elapsed_hr:.2f}h gainedA={gainedA} "
                f"gainedB={gainedB} combined_rate={rate:.1f}/hr threshold={CONSOLIDATE_RATE}/hr"
            )
            if rate <= CONSOLIDATE_RATE:
                consolidate(state)
            else:
                log("CONSOLIDATE-SKIP: rate above threshold; keeping both workers")

        if not second_hb_emitted and mono - state["start_mono"] >= 60:
            heartbeat(state)
            last_hb_mono = mono
            second_hb_emitted = True
        elif mono - last_hb_mono >= HB_SEC:
            heartbeat(state)
            last_hb_mono = mono


if __name__ == "__main__":
    main()
