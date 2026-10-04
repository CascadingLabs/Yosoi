#!/usr/bin/env python3
"""Bounded Linux /proc sampler; command lines are inspected transiently, never emitted."""
import argparse, csv, json, os, pathlib, time

ROLE_NAMES = ("controller", "browser", "renderer", "gpu", "utility", "other")
METRICS = ("rss_kib", "pss_kib", "cpu_ticks", "fd_count", "threads")

def read(path):
    try:
        return pathlib.Path(path).read_text(errors="replace")
    except OSError:
        return None

def stat(pid):
    value = read(f"/proc/{pid}/stat")
    if value is None:
        return None
    end = value.rfind(")")
    fields = value[end + 2:].split()
    try:
        return {"ppid": int(fields[1]), "utime_ticks": int(fields[11]), "stime_ticks": int(fields[12])}
    except (IndexError, ValueError):
        return None

def process_rows():
    rows = {}
    for name in os.listdir("/proc"):
        if name.isdigit():
            row = stat(name)
            if row:
                rows[int(name)] = row
    return rows

def descendants(root, rows):
    selected, changed = {root}, True
    while changed:
        changed = False
        for pid, row in rows.items():
            if row["ppid"] in selected and pid not in selected:
                selected.add(pid)
                changed = True
    return selected

def role_for(pid):
    if pid == ROOT:
        return "controller"
    # This value is used only to classify this sample and is never retained or emitted.
    command = (read(pathlib.Path("/proc") / str(pid) / "cmdline") or "").lower()
    if "--type=renderer" in command: return "renderer"
    if "--type=gpu-process" in command: return "gpu"
    if "--type=utility" in command: return "utility"
    if any(name in command for name in ("chromium", "chrome")): return "browser"
    return "other"

def metric(pid, rows):
    unavailable, values = [], {}
    status = read(f"/proc/{pid}/status") or ""
    for key, label in (("rss_kib", "VmRSS:"), ("threads", "Threads:")):
        line = next((line for line in status.splitlines() if line.startswith(label)), None)
        try: values[key] = int(line.split()[1])
        except (AttributeError, IndexError, ValueError): unavailable.append(key)
    smaps = read(f"/proc/{pid}/smaps_rollup")
    line = next((line for line in (smaps or "").splitlines() if line.startswith("Pss:")), None)
    try: values["pss_kib"] = int(line.split()[1])
    except (AttributeError, IndexError, ValueError): unavailable.append("pss_kib")
    try: values["fd_count"] = len(os.listdir(f"/proc/{pid}/fd"))
    except OSError: unavailable.append("fd_count")
    return {"pid": pid, "ppid": rows[pid]["ppid"], "role": role_for(pid), "cpu_ticks": rows[pid]["utime_ticks"] + rows[pid]["stime_ticks"], "unavailable": unavailable, **values}

def aggregate(processes):
    metrics = {}
    for key in METRICS:
        missing = [process["pid"] for process in processes if key not in process]
        metrics[key] = {"state": "unavailable", "value": None, "unavailable_pids": missing} if missing else {"state": "available", "value": sum(process[key] for process in processes), "unavailable_pids": []}
    role_counts = {role: sum(process["role"] == role for process in processes) for role in ROLE_NAMES}
    return {"metrics": metrics, "process_count": {"state": "available", "value": len(processes)}, "task_count": metrics["threads"], "role_counts": role_counts}

def sample(tracked):
    rows = process_rows()
    if os.path.exists(f"/proc/{ROOT}"):
        tracked.update(descendants(ROOT, rows))
    live = sorted(pid for pid in tracked if pid in rows)
    processes = [metric(pid, rows) for pid in live]
    return {"monotonic_ns": time.monotonic_ns(), "processes": processes, "aggregate": aggregate(processes)}

def peak(samples):
    output = {}
    for key in METRICS:
        values = [entry["aggregate"]["metrics"][key]["value"] for entry in samples if entry["aggregate"]["metrics"][key]["state"] == "available"]
        output[key] = {"state": "available", "value": max(values)} if values else {"state": "unavailable", "value": None}
    process_counts = [entry["aggregate"]["process_count"]["value"] for entry in samples]
    output["process_count"] = {"state": "available", "value": max(process_counts)} if process_counts else {"state": "unavailable", "value": None}
    output["role_counts"] = {role: max((entry["aggregate"]["role_counts"][role] for entry in samples), default=0) for role in ROLE_NAMES}
    return output

parser = argparse.ArgumentParser()
parser.add_argument("--pid", type=int, required=True)
parser.add_argument("--interval-ms", type=int, default=100)
parser.add_argument("--cleanup-grace-ms", type=int, default=2000)
parser.add_argument("--output", required=True)
parser.add_argument("--csv", required=True)
args = parser.parse_args()
ROOT = args.pid
interval = max(args.interval_ms, 1) / 1000
samples, tracked = [], {ROOT}
while os.path.exists(f"/proc/{ROOT}"):
    samples.append(sample(tracked))
    time.sleep(interval)
cleanup_deadline = time.monotonic() + max(args.cleanup_grace_ms, 0) / 1000
while True:
    entry = sample(tracked)
    samples.append(entry)
    remaining = [process["pid"] for process in entry["processes"]]
    if not remaining or time.monotonic() >= cleanup_deadline:
        break
    time.sleep(interval)
cleanup = {"grace_ms": max(args.cleanup_grace_ms, 0), "timed_out": bool(remaining), "remaining_pids": remaining, "remaining_count": len(remaining), "orphan_pids": [pid for pid in remaining if pid != ROOT]}
payload = {"controller_pid": ROOT, "samples": samples, "peak": peak(samples), "cleanup": cleanup}
pathlib.Path(args.output).write_text(json.dumps(payload, indent=2) + "\n")
with open(args.csv, "w", newline="") as output:
    writer = csv.writer(output)
    writer.writerow(["monotonic_ns", "rss_kib_state", "rss_kib", "pss_kib_state", "pss_kib", "cpu_ticks_state", "cpu_ticks", "fd_count_state", "fd_count", "task_count_state", "task_count", "process_count", "role_counts"])
    for entry in samples:
        aggregate = entry["aggregate"]; row = [entry["monotonic_ns"]]
        for key in ("rss_kib", "pss_kib", "cpu_ticks", "fd_count"):
            value = aggregate["metrics"][key]; row.extend((value["state"], value["value"] if value["value"] is not None else ""))
        tasks = aggregate["task_count"]
        row.extend((tasks["state"], tasks["value"] if tasks["value"] is not None else "", aggregate["process_count"]["value"], json.dumps(aggregate["role_counts"], sort_keys=True)))
        writer.writerow(row)
