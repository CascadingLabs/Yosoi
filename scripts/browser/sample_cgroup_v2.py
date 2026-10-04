#!/usr/bin/env python3
"""Sample a container's unified cgroup v2 without reading command lines or environments."""
import argparse
import csv
import json
from pathlib import Path
import re
import sys
import threading
import time

CPU_KEYS = ("usage_usec", "user_usec", "system_usec", "nr_throttled", "throttled_usec")
MEMORY_EVENT_KEYS = ("low", "high", "max", "oom", "oom_kill", "oom_group_kill")
PIDS_EVENT_KEYS = ("max",)
CGROUP_EVENT_KEYS = ("populated", "frozen")
DEVICE_PATTERN = re.compile(r"^[0-9]+:[0-9]+$")


def unavailable(error):
    return {"state": "unavailable", "value": None, "unavailable": [], "error": error}


def available(value, unavailable_keys=None):
    return {
        "state": "available",
        "value": value,
        "unavailable": unavailable_keys or [],
        "error": None,
    }


def read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace"), None
    except OSError as error:
        return None, error.strerror or error.__class__.__name__


def parse_key_values(path, required=()):
    text, error = read_text(path)
    if error is not None:
        return unavailable(error)
    values = {}
    invalid = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            values[parts[0]] = int(parts[1])
        except ValueError:
            invalid.append(parts[0])
    missing = [key for key in required if key not in values]
    return available(values, sorted(set(invalid + missing)))


def parse_number(path):
    text, error = read_text(path)
    if error is not None:
        return unavailable(error)
    try:
        return available(int(text.strip()))
    except ValueError:
        return unavailable("invalid integer")


def resolve_cgroup(pid):
    text, error = read_text(Path("/proc") / str(pid) / "cgroup")
    if error is not None:
        return None, error
    for line in text.splitlines():
        if line.startswith("0::"):
            relative = line[3:]
            components = [part for part in relative.split("/") if part]
            if any(part in (".", "..") for part in components):
                return None, "unsafe cgroup path"
            return Path("/sys/fs/cgroup", *components), None
    return None, "unified cgroup v2 entry not found"


def parse_io(path, wanted_devices, previous):
    text, error = read_text(path)
    if error is not None:
        return unavailable(error)
    devices = {}
    invalid = []
    for line in text.splitlines():
        fields = line.split()
        if not fields or not DEVICE_PATTERN.fullmatch(fields[0]):
            invalid.append(line)
            continue
        counters = {}
        for field in fields[1:]:
            key, separator, value = field.partition("=")
            if not separator:
                invalid.append(line)
                continue
            try:
                counters[key] = int(value)
            except ValueError:
                invalid.append(line)
        devices[fields[0]] = counters
    # With no explicit device filter, preserve all cgroup IO devices for matrix peaks.
    matched = devices if not wanted_devices else {device: devices[device] for device in wanted_devices if device in devices}
    deltas = {}
    for device, counters in matched.items():
        earlier = previous.get(device, {})
        deltas[device] = {key: value - earlier[key] for key, value in counters.items() if key in earlier}
    return {
        "state": "available",
        "raw": text,
        "devices": devices,
        "matched_devices": matched,
        "matched_device_deltas": deltas,
        "unavailable": sorted(wanted_devices - set(matched)),
        "error": None if not invalid else "one or more io.stat lines were invalid",
    }


def sample(cgroup, wanted_devices, previous_io, phase):
    now = time.monotonic_ns()
    if not cgroup.is_dir():
        return {
            "monotonic_ns": now,
            "phase": phase,
            "cgroup": unavailable("cgroup directory is absent"),
            "metrics": {},
        }
    io = parse_io(cgroup / "io.stat", wanted_devices, previous_io)
    metrics = {
        "cpu_stat": parse_key_values(cgroup / "cpu.stat", CPU_KEYS),
        "memory_current": parse_number(cgroup / "memory.current"),
        "memory_peak": parse_number(cgroup / "memory.peak"),
        "memory_events": parse_key_values(cgroup / "memory.events", MEMORY_EVENT_KEYS),
        "memory_stat": parse_key_values(cgroup / "memory.stat"),
        "pids_current": parse_number(cgroup / "pids.current"),
        "pids_peak": parse_number(cgroup / "pids.peak"),
        "pids_events": parse_key_values(cgroup / "pids.events", PIDS_EVENT_KEYS),
        "io_stat": io,
        "cgroup_events": parse_key_values(cgroup / "cgroup.events", CGROUP_EVENT_KEYS),
    }
    return {"monotonic_ns": now, "phase": phase, "cgroup": available(str(cgroup)), "metrics": metrics}


def peak_metric(samples, name):
    values = []
    for entry in samples:
        metric = entry["metrics"].get(name)
        if metric and metric.get("state") == "available":
            value = metric.get("value")
            if isinstance(value, int):
                values.append(value)
            elif isinstance(value, dict):
                values.append(value)
    if not values:
        return unavailable("no available samples")
    if isinstance(values[0], int):
        return available(max(values))
    keys = set().union(*(value.keys() for value in values))
    return available({key: max(value[key] for value in values if key in value) for key in sorted(keys)})


def peak_io(samples):
    devices = {}
    for entry in samples:
        io = entry["metrics"].get("io_stat", {})
        if io.get("state") != "available":
            continue
        for device, counters in io.get("matched_devices", {}).items():
            target = devices.setdefault(device, {})
            for key, value in counters.items():
                target[key] = max(target.get(key, value), value)
    return available(devices) if devices else unavailable("no available io samples")


def summary(samples):
    names = ("cpu_stat", "memory_current", "memory_peak", "memory_events", "memory_stat", "pids_current", "pids_peak", "pids_events", "cgroup_events")
    final = samples[-1] if samples else None
    return {
        "peak": {**{name: peak_metric(samples, name) for name in names}, "io_stat": peak_io(samples)},
        "final": final["metrics"] if final else {},
        "final_cgroup": final["cgroup"] if final else unavailable("no samples"),
    }


def write_outputs(output, csv_output, payload):
    output.parent.mkdir(parents=True, exist_ok=True)
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    output_tmp = output.with_name(output.name + ".tmp")
    csv_tmp = csv_output.with_name(csv_output.name + ".tmp")
    output_tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with csv_tmp.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["monotonic_ns", "phase", "cgroup_state", "cpu_usage_usec", "memory_current", "memory_peak", "pids_current", "io_stat_state", "io_matched_device_deltas"])
        for entry in payload["samples"]:
            metrics = entry["metrics"]
            def value(name):
                metric = metrics.get(name, {})
                return metric.get("value", "") if metric.get("state") == "available" else ""
            io = metrics.get("io_stat", {})
            writer.writerow([entry["monotonic_ns"], entry["phase"], entry["cgroup"]["state"], value("cpu_stat").get("usage_usec", "") if isinstance(value("cpu_stat"), dict) else "", value("memory_current"), value("memory_peak"), value("pids_current"), io.get("state", "unavailable"), json.dumps(io.get("matched_device_deltas", {}), sort_keys=True)])
    output_tmp.replace(output)
    csv_tmp.replace(csv_output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", required=True, type=int, help="container init PID")
    parser.add_argument("--output", required=True, type=Path, help="JSON output path")
    parser.add_argument("--csv", required=True, type=Path, help="CSV output path")
    parser.add_argument("--interval-ms", type=int, default=100)
    parser.add_argument("--cleanup-grace-ms", type=int, default=2000)
    parser.add_argument("--io-device", action="append", default=[], metavar="MAJOR:MINOR")
    args = parser.parse_args()
    if args.pid <= 0 or args.interval_ms <= 0 or args.cleanup_grace_ms < 0:
        parser.error("pid and interval-ms must be positive; cleanup-grace-ms must not be negative")
    if any(not DEVICE_PATTERN.fullmatch(device) for device in args.io_device):
        parser.error("--io-device must be MAJOR:MINOR")

    cgroup, resolution_error = resolve_cgroup(args.pid)
    samples = []
    wanted_devices = set(args.io_device)
    previous_io = {}
    if cgroup is None:
        samples.append({"monotonic_ns": time.monotonic_ns(), "phase": "running", "cgroup": unavailable(resolution_error), "metrics": {}})
        payload = {"container_init_pid": args.pid, "cgroup_v2": None, "resolution_error": resolution_error, "samples": samples, "summary": summary(samples), "cleanup": {"grace_ms": args.cleanup_grace_ms, "disappeared": False, "error": "cgroup could not be resolved"}}
        write_outputs(args.output, args.csv, payload)
        return 1

    interval_seconds = args.interval_ms / 1000.0
    timer = threading.Event()
    while Path("/proc", str(args.pid)).exists():
        entry = sample(cgroup, wanted_devices, previous_io, "running")
        samples.append(entry)
        io = entry["metrics"].get("io_stat", {})
        if io.get("state") == "available":
            previous_io = io["matched_devices"]
        timer.wait(interval_seconds)

    deadline = time.monotonic() + args.cleanup_grace_ms / 1000.0
    disappeared = False
    while True:
        entry = sample(cgroup, wanted_devices, previous_io, "cleanup_grace")
        samples.append(entry)
        io = entry["metrics"].get("io_stat", {})
        if io.get("state") == "available":
            previous_io = io["matched_devices"]
        if entry["cgroup"]["state"] == "unavailable":
            disappeared = True
            break
        if time.monotonic() >= deadline:
            break
        timer.wait(min(interval_seconds, max(0.0, deadline - time.monotonic())))

    payload = {"container_init_pid": args.pid, "cgroup_v2": str(cgroup), "resolution_error": None, "samples": samples, "summary": summary(samples), "cleanup": {"grace_ms": args.cleanup_grace_ms, "disappeared": disappeared, "timed_out": not disappeared, "error": None if disappeared else "cgroup remained after cleanup grace"}}
    write_outputs(args.output, args.csv, payload)
    return 0 if disappeared else 1


if __name__ == "__main__":
    sys.exit(main())
