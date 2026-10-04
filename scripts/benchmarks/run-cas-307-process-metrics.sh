#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
destination=${1:-$(scripts/benchmarks/benchmark-result-directory.sh process)}
iterations=${CAS307_PROCESS_ITERATIONS:-10}
source_snapshot_commit=$(jj log -r @ --no-graph -T 'commit_id' 2>/dev/null || git rev-parse HEAD)
jj_change_id=$(jj log -r @ --no-graph -T 'change_id' 2>/dev/null || printf 'not_detected')
parent=$(dirname "$destination")
mkdir -p "$parent" "$root/target"
exec 9>"$root/target/.capture-benchmark.lock"
if ! flock --nonblock 9; then
  printf 'another capture measurement is running; run measurement classes sequentially\n' >&2
  exit 1
fi
staging=$(mktemp -d "$parent/.cas-307-process-staging.XXXXXX")
cleanup() {
  status=$?
  trap - EXIT INT TERM
  rm -rf -- "$staging"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

value_or_unknown() {
  local value
  value=$("$@" 2>/dev/null || true)
  test -n "$value" && printf '%s' "$value" || printf 'unknown'
}
lscpu_field() {
  local value
  value=$(LC_ALL=C lscpu 2>/dev/null | awk -F: -v key="$1" '$1 == key {sub(/^[ \t]+/, "", $2); print $2; exit}')
  test -n "$value" && printf '%s' "$value" || printf 'unknown'
}

cargo build --jobs 1 --release -p yosoi-benchmarks --bin profile_capture
binary=target/release/profile_capture
test -x "$binary"
printf 'cargo build --jobs 1 --release -p yosoi-benchmarks --bin profile_capture\n' > "$staging/build-command.txt"
printf 'iterations=%s\n' "$iterations" > "$staging/run-settings.txt"

perf_events=task-clock,cycles,instructions,branches,branch-misses,cache-references,cache-misses,context-switches,page-faults
for workload in full compressed redirect truncated; do
  /usr/bin/time -v -o "$staging/time-$workload.txt" \
    "$binary" "$workload" "$iterations" > "$staging/stdout-$workload.txt"
  grep -Fq 'Maximum resident set size (kbytes):' "$staging/time-$workload.txt"
  grep -Fq 'Percent of CPU this job got:' "$staging/time-$workload.txt"
  set +e
  perf stat -x ';' -e "$perf_events" -o "$staging/perf-$workload.txt" -- \
    "$binary" "$workload" "$iterations" > "$staging/perf-stdout-$workload.txt" 2> "$staging/perf-stderr-$workload.txt"
  perf_status=$?
  set -e
  printf '%s\n' "$perf_status" > "$staging/perf-$workload.status"
done

scripts/benchmarks/summarize-cas-307-perf.py "$staging" "$iterations" "$staging/summary.csv"

manifest=benchmarks/fixtures/web-capture/v1/manifest.json
capture_fixture=benchmarks/fixtures/web-capture/v1/complete-capture-v1.json
manifest_digest=$(sha256sum "$manifest" | awk '{print $1}')
capture_fixture_digest=$(sha256sum "$capture_fixture" | awk '{print $1}')
printf '%s  %s\n%s  %s\n' "$manifest_digest" "$manifest" "$capture_fixture_digest" "$capture_fixture" > "$staging/fixture-inputs.sha256"
{
  printf 'captured_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'source_snapshot_commit=%s\n' "$source_snapshot_commit"
  printf 'jj_change_id=%s\n' "$jj_change_id"
  printf 'rustc=%s\ncargo=%s\n' "$(value_or_unknown rustc --version)" "$(value_or_unknown cargo --version)"
  printf 'gnu_time=%s\nperf=%s\n' "$(value_or_unknown /usr/bin/time --version | head -1)" "$(value_or_unknown perf --version)"
  printf 'target=%s\nprofile=release\nfeatures=default\nrustflags=%s\n' "$(rustc -vV 2>/dev/null | awk '/^host:/ {print $2}' || printf unknown)" "${RUSTFLAGS:-<unset>}"
  printf 'os=%s\nkernel=%s\narch=%s\n' "$(value_or_unknown uname -s)" "$(value_or_unknown uname -r)" "$(value_or_unknown uname -m)"
  printf 'cpu_model=%s\nlogical_cpu_count=%s\n' "$(lscpu_field 'Model name')" "$(value_or_unknown getconf _NPROCESSORS_ONLN)"
  printf 'perf_event_paranoid=%s\n' "$(value_or_unknown cat /proc/sys/kernel/perf_event_paranoid)"
  printf 'process_scope=one fresh process performing %s sequential loopback captures\n' "$iterations"
  printf 'network_control=IPv4 loopback only; no public network\n'
} > "$staging/environment.txt"
{
  printf '# CAS-307 process resource baseline\n\n'
  printf 'Exploratory fresh-process evidence for `%s` sequential captures per workload. Peak RSS is not peak heap. GNU time CPU percentage is process utilization over elapsed time, not host-wide utilization.\n\n' "$iterations"
  printf '## Environment\n```text\n'; cat "$staging/environment.txt"; printf '```\n\n'
  printf '## Fixture digests\n```text\n'; cat "$staging/fixture-inputs.sha256"; printf '```\n\n'
  printf '## Normalized summary\n```csv\n'; cat "$staging/summary.csv"; printf '```\n\n'
  for workload in full compressed redirect truncated; do
    printf '## %s\n\n```text\n' "$workload"
    grep -E 'User time|System time|Percent of CPU|Elapsed \(wall clock\)|Maximum resident set size|Major .*page faults|Minor .*page faults|Voluntary context switches|Involuntary context switches' "$staging/time-$workload.txt"
    printf '```\n\n'
    perf_status=$(cat "$staging/perf-$workload.status")
    counter_status=$(awk -F, -v workload="$workload" '$1 == workload {print $4}' "$staging/summary.csv")
    if test "$counter_status" = available; then
      printf 'Validated numeric hardware/software counter output is retained in `perf-%s.txt`.\n\n' "$workload"
    else
      printf 'Hardware/software counters unavailable or nonnumeric (`perf stat` exit %s); diagnostics retained in `perf-%s.txt` and `perf-stderr-%s.txt`.\n\n' "$perf_status" "$workload" "$workload"
    fi
  done
} > "$staging/baseline.md"
scripts/fixtures/normalize-benchmark-text.py "$staging"

scripts/benchmarks/publish-benchmark-result.sh "$staging" "$destination"
trap - EXIT INT TERM
scripts/benchmarks/summarize-benchmark-change.py "$(dirname "$destination")"
