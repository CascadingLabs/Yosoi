#!/usr/bin/env python3
"""Validate perf-stat CSV and publish numeric or explicitly unavailable summaries."""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

WORKLOADS = ("full", "compressed", "redirect", "truncated")
REQUIRED = ("task-clock", "cycles", "instructions", "cache-misses")


def metric_values(path: Path) -> dict[str, Decimal]:
    values: dict[str, Decimal] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter=";"):
            if len(row) < 3:
                continue
            event = row[2].split(":", 1)[0]
            if event not in REQUIRED:
                continue
            raw = row[0].strip()
            try:
                value = Decimal(raw)
            except InvalidOperation:
                continue
            if not value.is_finite() or value < 0:
                continue
            values[event] = value
    return values


def peak_rss(path: Path) -> int:
    prefix = "Maximum resident set size (kbytes):"
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return int(stripped.removeprefix(prefix).strip())
    raise ValueError(f"missing peak RSS in {path}")


def summarize(directory: Path, iterations: int, output: Path) -> None:
    fields = (
        "workload",
        "iterations",
        "peak_rss_kib",
        "counter_status",
        "task_clock_ms",
        "total_cycles",
        "cycles_per_capture",
        "total_instructions",
        "instructions_per_capture",
        "cache_misses",
    )
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for workload in WORKLOADS:
            row: dict[str, object] = {
                "workload": workload,
                "iterations": iterations,
                "peak_rss_kib": peak_rss(directory / f"time-{workload}.txt"),
            }
            status = int((directory / f"perf-{workload}.status").read_text().strip())
            values = metric_values(directory / f"perf-{workload}.txt") if status == 0 else {}
            missing = [metric for metric in REQUIRED if metric not in values]
            if status != 0 or missing:
                row.update(
                    counter_status="unavailable",
                    task_clock_ms="unavailable",
                    total_cycles="unavailable",
                    cycles_per_capture="unavailable",
                    total_instructions="unavailable",
                    instructions_per_capture="unavailable",
                    cache_misses="unavailable",
                )
            else:
                row.update(
                    counter_status="available",
                    task_clock_ms=values["task-clock"],
                    total_cycles=values["cycles"],
                    cycles_per_capture=values["cycles"] / iterations,
                    total_instructions=values["instructions"],
                    instructions_per_capture=values["instructions"] / iterations,
                    cache_misses=values["cache-misses"],
                )
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("iterations", type=int)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    if arguments.iterations <= 0:
        parser.error("iterations must be greater than zero")
    summarize(arguments.directory, arguments.iterations, arguments.output)


if __name__ == "__main__":
    main()
