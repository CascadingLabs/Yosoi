#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
destination=${1:-$(scripts/benchmarks/benchmark-result-directory.sh callgrind)}
runner=$(command -v gungraun-runner || true)
valgrind=$(command -v valgrind || true)
if test -z "$runner"; then
  printf 'gungraun-runner is required; install 0.19.4 with cargo install\n' >&2
  exit 1
fi
if test -z "$valgrind"; then
  printf 'Valgrind is required for Callgrind measurements\n' >&2
  exit 1
fi

source_snapshot_commit=$(jj log -r @ --no-graph -T 'commit_id' 2>/dev/null || git rev-parse HEAD)
jj_change_id=$(jj log -r @ --no-graph -T 'change_id' 2>/dev/null || printf 'not_detected')
parent=$(dirname "$destination")
mkdir -p "$parent" "$root/target"
exec 9>"$root/target/.capture-benchmark.lock"
if ! flock --nonblock 9; then
  printf 'another capture measurement is running; run measurement classes sequentially\n' >&2
  exit 1
fi
staging=$(mktemp -d "$parent/.cas-307-gungraun-staging.XXXXXX")
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

manifest=benchmarks/fixtures/web-capture/v1/manifest.json
capture_fixture=benchmarks/fixtures/web-capture/v1/complete-capture-v1.json
manifest_digest=$(sha256sum "$manifest" | awk '{print $1}')
capture_fixture_digest=$(sha256sum "$capture_fixture" | awk '{print $1}')
rm -rf target/gungraun/yosoi-benchmarks/gungraun_capture
command=(cargo bench --jobs 1 -p yosoi-benchmarks --bench gungraun_capture -- --save-summary=pretty-json)
printf '%q ' "${command[@]}" > "$staging/command.txt"
printf '\n' >> "$staging/command.txt"
GUNGRAUN_RUNNER="$runner" "${command[@]}" 2>&1 | tee "$staging/gungraun-output.txt"
raw=target/gungraun/yosoi-benchmarks/gungraun_capture
if ! test -d "$raw"; then
  printf 'Gungraun produced no output directory\n' >&2
  exit 1
fi
cp -R "$raw" "$staging/gungraun-raw"
(cd "$staging" && find gungraun-raw -name summary.json -type f | sort) > "$staging/summaries.txt"
test "$(wc -l < "$staging/summaries.txt")" -eq 4
for benchmark in sha256_large_html serialize_canonical_capture deserialize_canonical_capture finalize_large_source; do
  grep -Fq "/$benchmark/summary.json" "$staging/summaries.txt"
done
printf '%s  %s\n%s  %s\n' "$manifest_digest" "$manifest" "$capture_fixture_digest" "$capture_fixture" > "$staging/fixture-inputs.sha256"
{
  printf 'captured_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'source_snapshot_commit=%s\n' "$source_snapshot_commit"
  printf 'jj_change_id=%s\n' "$jj_change_id"
  printf 'rustc=%s\n' "$(value_or_unknown rustc --version)"
  printf 'cargo=%s\n' "$(value_or_unknown cargo --version)"
  printf 'gungraun=%s\n' '0.19.4'
  printf 'gungraun_runner=%s\n' "$(value_or_unknown "$runner" --version)"
  printf 'valgrind=%s\n' "$(value_or_unknown "$valgrind" --version)"
  printf 'target=%s\n' "$(rustc -vV 2>/dev/null | awk '/^host:/ {print $2}' || printf unknown)"
  printf 'profile=bench\nfeatures=default\nrustflags=%s\n' "${RUSTFLAGS:-<unset>}"
  printf 'os=%s\nkernel=%s\narch=%s\n' "$(value_or_unknown uname -s)" "$(value_or_unknown uname -r)" "$(value_or_unknown uname -m)"
  printf 'cpu_model=%s\nlogical_cpu_count=%s\n' "$(lscpu_field 'Model name')" "$(value_or_unknown getconf _NPROCESSORS_ONLN)"
  printf 'cache_model=Gungraun default simulated cache hierarchy; see summary JSON\n'
  printf 'network_control=no network; fixed local fixture files only\n'
} > "$staging/environment.txt"
if grep -Ev '^[a-z0-9_]+=.*$' "$staging/environment.txt"; then
  printf 'invalid environment metadata line\n' >&2
  exit 1
fi
{
  printf '# CAS-307 Gungraun Callgrind baseline\n\n'
  printf 'Exploratory one-shot instruction and modeled-cache evidence; no regression threshold is implied.\n\n'
  printf '## Environment\n```text\n'; cat "$staging/environment.txt"; printf '```\n\n'
  printf '## Fixture digests\n```text\n'; cat "$staging/fixture-inputs.sha256"; printf '```\n\n'
  printf '## Output\n```text\n'; cat "$staging/gungraun-output.txt"; printf '```\n\n'
  printf 'Raw Callgrind files and machine-readable per-benchmark summaries are retained under `gungraun-raw/`.\n'
} > "$staging/baseline.md"
scripts/fixtures/normalize-benchmark-text.py "$staging"

scripts/benchmarks/publish-benchmark-result.sh "$staging" "$destination"
trap - EXIT INT TERM
scripts/benchmarks/summarize-benchmark-change.py "$(dirname "$destination")"
