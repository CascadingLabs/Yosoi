#!/usr/bin/env python3
"""Build an at-a-glance Markdown and CSV dashboard for one local benchmark change."""
from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class Metric:
    layer: str
    tool: str
    workload: str
    metric: str
    value: str
    unit: str
    scope: str
    status: str
    source: str


CRITERION_CASES = {
    "sha256_large_html": "sha256_only/encoded_bytes/large-html/new/estimates.json",
    "body_identity_medium_html": "yosoi_consume_response_body_pipeline/identity/medium-html/new/estimates.json",
    "body_gzip_medium_html": "yosoi_consume_response_body_pipeline/gzip/medium-html-gzip/new/estimates.json",
    "body_brotli_medium_html": "yosoi_consume_response_body_pipeline/br/medium-html-br/new/estimates.json",
    "body_gzip_high_ratio": "yosoi_consume_response_body_pipeline/gzip/large-high-ratio-gzip/new/estimates.json",
    "classify_decode_large_html": "source_classification_character_decode/validated_binding_classify_decode/large-html/new/estimates.json",
    "classify_decode_large_xml": "source_classification_character_decode/validated_binding_classify_decode/large-xml/new/estimates.json",
    "classify_decode_large_json": "source_classification_character_decode/validated_binding_classify_decode/large-json/new/estimates.json",
    "classify_decode_large_plain": "source_classification_character_decode/validated_binding_classify_decode/large-plain/new/estimates.json",
    "wire_serialize": "canonical_web_capture_wire/serialize_complete_capture/new/estimates.json",
    "wire_deserialize": "canonical_web_capture_wire/deserialize_complete_capture/new/estimates.json",
    "finalize_large_source": "capture_finalization_bundle_retained/complete_source_only_large-html/availability_retained__retained_bytes_262144/new/estimates.json",
    "raw_wreq_medium_html": "local_raw_wreq_construct_request_and_exact_body_consumption/medium_html/new/estimates.json",
    "full_capture_medium_html": "full_capture_direct_http_including_hardened_client_construction/medium_html_same_headers_body_and_close/new/estimates.json",
    "redirect_one_hop": "full_capture_redirect_chain/one_hop_exact_limit_success/configured_max_hops_1/new/estimates.json",
    "redirect_three_hops": "full_capture_redirect_chain/three_hops_exact_limit_success/configured_max_hops_3/new/estimates.json",
}


def criterion_metrics(change: Path) -> list[Metric]:
    root = change / "criterion/criterion-raw"
    metrics = []
    for workload, relative in CRITERION_CASES.items():
        path = root / relative
        if not path.is_file():
            continue
        estimate = json.loads(path.read_text(encoding="utf-8"))["median"]["point_estimate"]
        metrics.append(Metric("L0", "Criterion", workload, "median_wall_time", str(estimate), "ns", "in_process", "available", str(path.relative_to(change))))
    return metrics


def callgrind_metrics(change: Path) -> list[Metric]:
    metrics = []
    for path in sorted((change / "callgrind").glob("gungraun-raw/**/summary.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        workload = document["function_name"]
        summary = document["profiles"][0]["summaries"]["parts"][0]["metrics_summary"]["Callgrind"]
        for key, name, unit in (("Ir", "modeled_instructions", "instructions"), ("EstimatedCycles", "estimated_cycles", "cycles"), ("L1HitRate", "modeled_l1_hit_rate", "percent"), ("LLMissRate", "modeled_last_level_miss_rate", "percent")):
            value = summary[key]["metrics"]["Left"]
            number = value.get("Int", value.get("Float"))
            metrics.append(Metric("L0", "Gungraun/Callgrind", workload, name, str(number), unit, "in_process_one_shot", "available", str(path.relative_to(change))))
    return metrics


def parse_divan_file(path: Path, layer: str, tool: str, scope: str) -> list[Metric]:
    if not path.is_file():
        return []
    benchmarks: dict[str, dict[str, tuple[str, str]]] = {}
    parent: str | None = None
    current: str | None = None
    category: str | None = None
    pending: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parent_match = re.match(r"^[├╰]─\s+(\S+)", line)
        leaf_match = re.match(r"^│  [├╰]─\s+(.+?)\s{2,}", line)
        if parent_match:
            parent = parent_match.group(1)
            current = parent
            benchmarks.setdefault(current, {})
            category = None
            pending = []
            continue
        if leaf_match and parent is not None:
            leaf = leaf_match.group(1).strip()
            current = f"{parent}/{leaf}"
            benchmarks.setdefault(current, {})
            category = None
            pending = []
            continue
        if current is None:
            continue
        stripped = line.replace("│", " ").strip()
        if stripped in {"max alloc:", "alloc:", "dealloc:", "grow:", "shrink:"}:
            category = stripped.removesuffix(":").replace(" ", "_")
            pending = []
            continue
        if category not in {"max_alloc", "alloc", "grow"}:
            continue
        columns = [column.strip() for column in line.split("│") if column.strip()]
        first = columns[0] if columns else ""
        if re.fullmatch(r"[0-9]+", first):
            pending = [first]
        elif pending and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?\s+(?:B|KB|MB|GB)", first):
            benchmarks[current][category] = (pending[0], str(size_bytes(first)))
            pending = []
    rows = []
    for workload, values in benchmarks.items():
        if not values:
            continue
        maximum = values.get("max_alloc", ("0", "0"))
        allocated = values.get("alloc", ("0", "0"))
        grown = values.get("grow", ("0", "0"))
        total_allocated_bytes = str(int(allocated[1]) + int(grown[1]))
        for metric, value, unit in (
            ("allocation_operations", allocated[0], "count"),
            ("growth_operations", grown[0], "count"),
            ("allocated_bytes", allocated[1], "bytes"),
            ("grown_bytes", grown[1], "bytes"),
            ("total_allocated_bytes", total_allocated_bytes, "bytes"),
            ("maximum_live_allocations", maximum[0], "count"),
            ("maximum_live_bytes", maximum[1], "bytes"),
        ):
            rows.append(Metric(layer, tool, workload, metric, value, unit, scope, "available", str(path)))
    return rows


def parse_divan(change: Path) -> list[Metric]:
    path = change / "allocations/allocation-output.txt"
    rows = parse_divan_file(path, "L0", "Divan AllocProfiler", "synchronous_benchmark_thread")
    return [Metric(item.layer, item.tool, item.workload, item.metric, item.value, item.unit, item.scope, item.status, str(path.relative_to(change))) for item in rows]


def size_bytes(value: str) -> int:
    number, unit = value.split()
    multiplier = {"B": 1, "KB": 1_000, "MB": 1_000_000, "GB": 1_000_000_000}[unit]
    return int(Decimal(number) * multiplier)


def csv_metrics(change: Path, directory: str, layer: str, tool: str, scope: str) -> list[Metric]:
    path = change / directory / "summary.csv"
    if not path.is_file():
        return []
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for record in csv.DictReader(handle):
            workload = record["workload"]
            status = record.get("counter_status", "available")
            ignored = {"workload", "iterations", "counter_status", "snapshot"}
            for metric, value in record.items():
                if metric in ignored or value in (None, ""):
                    continue
                unit = "bytes" if "bytes" in metric else "count"
                if metric == "peak_rss_kib":
                    unit = "KiB"
                elif metric == "task_clock_ms":
                    unit = "ms"
                elif "cycles" in metric:
                    unit = "cycles"
                elif "instructions" in metric:
                    unit = "instructions"
                metric_status = status if metric not in {"peak_rss_kib"} else "available"
                rows.append(Metric(layer, tool, workload, metric, value, unit, scope, metric_status, str(path.relative_to(change))))
    return rows


def browser_criterion_metrics(change: Path) -> list[Metric]:
    root = change / "browser/criterion-raw"
    metrics = []
    for path in sorted(root.glob("**/new/estimates.json")):
        try:
            estimate = json.loads(path.read_text(encoding="utf-8"))["median"]["point_estimate"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        workload = "/".join(path.relative_to(root).parts[:-2])
        metrics.append(Metric("L2", "Browser Criterion", workload, "median_wall_time", str(estimate), "ns", "browser_in_process", "available", str(path.relative_to(change))))
    return metrics


def browser_divan_metrics(change: Path) -> list[Metric]:
    path = change / "browser/allocation-output.txt"
    rows = parse_divan_file(path, "L2", "Browser Divan AllocProfiler", "synchronous_benchmark_thread")
    return [Metric(item.layer, item.tool, item.workload, item.metric, item.value, item.unit, item.scope, item.status, str(path.relative_to(change))) for item in rows]


def browser_soak_metrics(change: Path) -> list[Metric]:
    rows = []
    native_units = {
        "attempts": "count",
        "finalization_failures": "count",
        "elapsed_p50_ms": "ms",
        "elapsed_p95_ms": "ms",
        "elapsed_p99_ms": "ms",
        "cancellation_to_return_p50_ms": "ms",
        "cancellation_to_return_p95_ms": "ms",
        "cancellation_to_return_p99_ms": "ms",
        "peak_rss_kib": "KiB",
        "peak_pss_kib": "KiB",
        "peak_cpu_ticks": "ticks",
        "peak_fd_count": "count",
        "peak_task_count": "count",
        "peak_process_count": "count",
        "cleanup_remaining_count": "count",
        "cleanup_timed_out": "boolean",
    }
    for environment in ("native-headless", "native-headful"):
        path = change / "browser" / environment / "summary.csv"
        if not path.is_file():
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            for record in csv.DictReader(handle):
                workload = f"{environment}/{record.get('workload_cell', record.get('workload', 'unknown'))}/c{record.get('concurrency', 'unknown')}"
                for metric, unit in native_units.items():
                    value = record.get(metric)
                    if value not in (None, ""):
                        scope = "browser_cleanup" if metric.startswith("cleanup_") else "native_browser_process_tree"
                        rows.append(Metric("L2", "Native browser soak", workload, metric, value, unit, scope, "available", str(path.relative_to(change))))
    container_units = {
        "attempt_count": "count",
        "elapsed_p50_ms": "ms",
        "elapsed_p95_ms": "ms",
        "elapsed_p99_ms": "ms",
        "cancellation_return_p50_ms": "ms",
        "cancellation_return_p95_ms": "ms",
        "cancellation_return_p99_ms": "ms",
        "cpu_usage_peak_usec": "us",
        "memory_peak_bytes": "bytes",
        "pids_peak": "count",
        "cpu_nr_throttled_peak": "count",
        "cpu_throttled_peak_usec": "us",
        "container_exit": "code",
    }
    for environment in ("container-headless", "container-headful"):
        path = change / "browser" / environment / "summary.csv"
        if not path.is_file():
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            for record in csv.DictReader(handle):
                workload = f"{environment}/{record.get('workload', 'unknown')}/c{record.get('concurrency', 'unknown')}"
                for metric, unit in container_units.items():
                    value = record.get(metric)
                    if value not in (None, ""):
                        rows.append(Metric("L2", "Container browser soak", workload, metric, value, unit, "container_cgroup_v2", "available", str(path.relative_to(change))))
                for metric in ("record_result", "cleanup", "finalization_results", "attempt_cleanup_results", "memory_events_peak", "pids_events_peak", "io_peak"):
                    value = record.get(metric)
                    if value not in (None, ""):
                        rows.append(Metric("L2", "Container browser soak", workload, metric, value, "state", "container_cgroup_v2", "available", str(path.relative_to(change))))
    return rows


def source_snapshots(change: Path) -> list[str]:
    values = set()
    for path in change.glob("*/environment.txt"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("source_snapshot_commit="):
                values.add(line.split("=", 1)[1])
    return sorted(values)


def write_csv(path: Path, metrics: list[Metric]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(Metric.__annotations__.keys())
        for metric in metrics:
            writer.writerow(metric.__dict__.values())


def display(value: str, unit: str) -> str:
    try:
        number = Decimal(value)
    except Exception:
        return value
    if unit == "ns":
        if number >= 1_000_000:
            return f"{number / 1_000_000:.3f} ms"
        if number >= 1_000:
            return f"{number / 1_000:.3f} µs"
        return f"{number:.1f} ns"
    if unit == "bytes":
        return f"{number / 1_000_000:.3f} MB" if number >= 1_000_000 else f"{number / 1_000:.3f} KB"
    if unit == "KiB":
        return f"{number / Decimal(1024):.2f} MiB"
    if unit == "percent":
        return f"{number:.4f}%"
    return f"{number.normalize()} {unit}"


def markdown(change: Path, metrics: list[Metric]) -> str:
    lines = [
        "# Benchmark summary",
        "",
        f"VCS result group: `{change}`",
        "",
        "These are local, exploratory measurements—not universal thresholds. Compare changes only when fixture digests, toolchain, profile, and relevant environment metadata agree.",
        "",
        "## At a glance",
        "",
    ]
    sections = (
        ("Wall time", "Criterion", ("median_wall_time",)),
        ("Deterministic CPU model", "Gungraun/Callgrind", ("modeled_instructions", "estimated_cycles")),
        ("Allocations", "Divan AllocProfiler", ("allocation_operations", "total_allocated_bytes", "maximum_live_bytes")),
        ("Fresh-process resources and hardware", "GNU time + perf", ("peak_rss_kib", "task_clock_ms", "instructions_per_capture", "cycles_per_capture", "cache_misses")),
        ("Fresh-process heap", "Massif", ("peak_heap_bytes", "peak_heap_extra_bytes", "stack_bytes_at_heap_peak")),
        ("Browser wall time", "Browser Criterion", ("median_wall_time",)),
        ("Browser allocations", "Browser Divan AllocProfiler", ("allocation_operations", "total_allocated_bytes", "maximum_live_bytes")),
        ("Native browser soak process tree", "Native browser soak", ("attempts", "elapsed_p50_ms", "elapsed_p95_ms", "elapsed_p99_ms", "peak_rss_kib", "peak_pss_kib", "peak_fd_count", "peak_task_count", "peak_process_count", "cleanup_timed_out", "cleanup_remaining_count")),
        ("Container browser cgroup v2", "Container browser soak", ("attempt_count", "elapsed_p50_ms", "elapsed_p95_ms", "elapsed_p99_ms", "memory_peak_bytes", "pids_peak", "cpu_usage_peak_usec", "cpu_nr_throttled_peak", "cpu_throttled_peak_usec", "container_exit")),
    )
    for title, tool, names in sections:
        selected = [item for item in metrics if item.tool == tool and item.metric in names]
        if not selected:
            continue
        lines += [f"### {title}", "", "| Workload | Metric | Value | Scope |", "|---|---|---:|---|"]
        for item in selected:
            value = display(item.value, item.unit) if item.status == "available" else "unavailable"
            lines.append(f"| `{item.workload}` | `{item.metric}` | {value} | `{item.scope}` |")
        lines.append("")
    snapshots = source_snapshots(change)
    lines += ["## Provenance", "", "Exact measured source snapshots:", ""]
    lines.extend(f"- `{snapshot}`" for snapshot in snapshots)
    lines += [
        "",
        "Each measurement directory contains `environment.txt`, `fixture-inputs.sha256`, raw/normalized evidence, and its detailed `baseline.md`. Prior successful capture runs are retained under `history/<class>/`; this dashboard shows only the latest run of each class.",
        "",
        "## Interpretation boundaries",
        "",
        "- Criterion is wall-clock evidence; Divan timing is allocator-instrumented and not a Criterion substitute.",
        "- Callgrind instructions/cache values are deterministic models, not hardware counters or elapsed time.",
        "- Divan allocation scope is the synchronous benchmark thread, not Tokio workers or browser child processes.",
        "- GNU time peak RSS covers this Yosoi benchmark process, including its loopback fixture server; it is not peak heap.",
        "- Massif is highly perturbing and includes process/runtime heap outside the capture operation.",
        "- Browser benchmarks require cgroup or PID-tree RSS/PSS/CPU/FD/task accounting; controller-process RSS is insufficient.",
        "",
        "See `summary.csv` for the complete normalized metric set and each measurement subdirectory for raw evidence.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("change_directory", type=Path)
    arguments = parser.parse_args()
    change = arguments.change_directory
    change.mkdir(parents=True, exist_ok=True)
    metrics = criterion_metrics(change)
    metrics += callgrind_metrics(change)
    metrics += parse_divan(change)
    metrics += csv_metrics(change, "process", "L1", "GNU time + perf", "fresh_process_10_sequential_captures")
    metrics += csv_metrics(change, "heap", "L1", "Massif", "fresh_process_one_capture")
    metrics += browser_criterion_metrics(change)
    metrics += browser_divan_metrics(change)
    metrics += browser_soak_metrics(change)
    metrics.sort(key=lambda item: (item.layer, item.tool, item.workload, item.metric))
    write_csv(change / "summary.csv", metrics)
    (change / "README.md").write_text(markdown(change, metrics), encoding="utf-8")


if __name__ == "__main__":
    main()
