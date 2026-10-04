#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
destination=${1:-$(scripts/benchmarks/benchmark-result-directory.sh heap)}
if ! command -v ms_print >/dev/null 2>&1; then
  printf 'ms_print is required to render Massif reports\n' >&2
  exit 1
fi
parent=$(dirname "$destination")
mkdir -p "$parent" "$root/target"
exec 9>"$root/target/.capture-benchmark.lock"
if ! flock --nonblock 9; then
  printf 'another capture measurement is running; run measurement classes sequentially\n' >&2
  exit 1
fi
staging=$(mktemp -d "$parent/.cas-307-heap-staging.XXXXXX")
cleanup() {
  status=$?
  trap - EXIT INT TERM
  rm -rf -- "$staging"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

cargo build --jobs 1 --release -p yosoi-benchmarks --bin profile_capture
binary=target/release/profile_capture
printf 'workload,peak_heap_bytes,peak_heap_extra_bytes,stack_bytes_at_heap_peak,snapshot\n' > "$staging/summary.csv"
for workload in full compressed redirect truncated; do
  output="$staging/massif-$workload.out"
  log="$staging/massif-$workload.log"
  valgrind --tool=massif --stacks=yes --time-unit=i \
    --massif-out-file="$output" --log-file="$log" -- "$binary" "$workload" 1 \
    > "$staging/stdout-$workload.txt"
  python3 - "$workload" "$output" >> "$staging/summary.csv" <<'PY'
import sys
workload, path = sys.argv[1:]
snapshots = []
current = {}
for line in open(path, encoding="utf-8"):
    line = line.strip()
    if line.startswith("snapshot="):
        if current:
            snapshots.append(current)
        current = {"snapshot": int(line.split("=", 1)[1])}
    elif "=" in line:
        key, value = line.split("=", 1)
        if key in {"mem_heap_B", "mem_heap_extra_B", "mem_stacks_B"}:
            current[key] = int(value)
if current:
    snapshots.append(current)
if not snapshots:
    raise SystemExit("Massif produced no snapshots")
peak = max(snapshots, key=lambda item: item.get("mem_heap_B", 0))
print(",".join(str(value) for value in (
    workload,
    peak.get("mem_heap_B", 0),
    peak.get("mem_heap_extra_B", 0),
    peak.get("mem_stacks_B", 0),
    peak["snapshot"],
)))
PY
  ms_print "$output" > "$staging/massif-$workload.txt"
  gzip -n -9 "$output" "$staging/massif-$workload.txt"
done

source_snapshot_commit=$(jj log -r @ --no-graph -T 'commit_id' 2>/dev/null || git rev-parse HEAD)
jj_change_id=$(jj log -r @ --no-graph -T 'change_id' 2>/dev/null || printf 'not_detected')
manifest=benchmarks/fixtures/web-capture/v1/manifest.json
capture_fixture=benchmarks/fixtures/web-capture/v1/complete-capture-v1.json
manifest_digest=$(sha256sum "$manifest" | awk '{print $1}')
capture_fixture_digest=$(sha256sum "$capture_fixture" | awk '{print $1}')
printf '%s  %s\n%s  %s\n' "$manifest_digest" "$manifest" "$capture_fixture_digest" "$capture_fixture" > "$staging/fixture-inputs.sha256"
{
  printf 'captured_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'source_snapshot_commit=%s\njj_change_id=%s\n' "$source_snapshot_commit" "$jj_change_id"
  printf 'rustc=%s\nvalgrind=%s\n' "$(rustc --version)" "$(valgrind --version)"
  printf 'target=%s\nprofile=release\n' "$(rustc -vV | awk '/^host:/ {print $2}')"
  printf 'massif_scope=fresh process performing one loopback capture; stacks enabled; instruction time unit\n'
  printf 'network_control=IPv4 loopback only; no public network\n'
} > "$staging/environment.txt"
{
  printf '# CAS-307 Massif peak-heap baseline\n\n'
  printf 'Exploratory fresh-process peak heap evidence for one capture per workload. This is not peak RSS and includes runtime/process heap outside the capture operation.\n\n'
  printf '## Environment\n```text\n'; cat "$staging/environment.txt"; printf '```\n\n'
  printf '## Fixture digests\n```text\n'; cat "$staging/fixture-inputs.sha256"; printf '```\n\n'
  printf '## Peak snapshot summary\n```csv\n'; cat "$staging/summary.csv"; printf '```\n\n'
  printf 'Deterministically compressed raw Massif profiles and `ms_print` reports are retained beside this summary.\n'
} > "$staging/baseline.md"
scripts/fixtures/normalize-benchmark-text.py "$staging"

scripts/benchmarks/publish-benchmark-result.sh "$staging" "$destination"
trap - EXIT INT TERM
scripts/benchmarks/summarize-benchmark-change.py "$(dirname "$destination")"
