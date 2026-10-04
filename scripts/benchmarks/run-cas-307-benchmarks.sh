#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
destination=${1:-$(scripts/benchmarks/benchmark-result-directory.sh criterion)}
# Capture the immutable source snapshot before creating or publishing result files. JJ may
# rewrite the working-copy commit when generated files subsequently enter the workspace.
source_snapshot_commit=$(jj log -r @ --no-graph -T 'commit_id' 2>/dev/null || git rev-parse HEAD)
jj_change_id=$(jj log -r @ --no-graph -T 'change_id' 2>/dev/null || printf 'not_detected')
parent=$(dirname "$destination")
mkdir -p "$parent" "$root/target"
exec 9>"$root/target/.capture-benchmark.lock"
if ! flock --nonblock 9; then
  printf 'another capture measurement is running; run measurement classes sequentially\n' >&2
  exit 1
fi
staging=$(mktemp -d "$parent/.cas-307-staging.XXXXXX")
cleanup() {
  status=$?
  trap - EXIT INT TERM
  rm -rf -- "$staging"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

value_or_unknown() { local value; value=$("$@" 2>/dev/null || true); test -n "$value" && printf '%s' "$value" || printf 'unknown'; }
lscpu_field() { local value; value=$(LC_ALL=C lscpu 2>/dev/null | awk -F: -v key="$1" '$1 == key {sub(/^[ \t]+/, "", $2); print $2; exit}'); test -n "$value" && printf '%s' "$value" || printf 'unknown'; }

manifest=benchmarks/fixtures/web-capture/v1/manifest.json
capture_fixture=benchmarks/fixtures/web-capture/v1/complete-capture-v1.json
manifest_digest=$(sha256sum "$manifest" | awk '{print $1}')
capture_fixture_digest=$(sha256sum "$capture_fixture" | awk '{print $1}')
virtualization=$(lscpu_field Virtualization)
container=not_detected
if test -f /.dockerenv; then
  container=docker
elif test -f /run/.containerenv; then
  container=containerenv
elif command -v systemd-detect-virt >/dev/null 2>&1; then
  detected_container=$(systemd-detect-virt --container 2>/dev/null || true)
  container=${detected_container:-not_detected}
fi
power_control=unknown
if test -r /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor; then power_control="governor=$(value_or_unknown head -n 1 /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"; elif test -d /sys/devices/system/cpu/cpu0/cpufreq; then power_control=available_status_unknown; else power_control=not_detected; fi
{
  printf 'captured_utc=%s\nsource_snapshot_commit=%s\njj_change_id=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$source_snapshot_commit" "$jj_change_id"
  printf 'source_snapshot_note=immutable code+fixtures measured; generated result publication may rewrite the current JJ working-copy commit, so this need not equal the post-publication commit\n'
  printf 'rustc=%s\ncargo=%s\ncriterion=0.7.0\n' "$(value_or_unknown rustc --version)" "$(value_or_unknown cargo --version)"
  printf 'target=%s\nprofile=bench\nfeatures=default\nrustflags=%s\n' "$(rustc -vV 2>/dev/null | awk '/^host:/ {print $2}' || printf 'unknown')" "${RUSTFLAGS:-<unset>}"
  printf 'os=%s\nkernel=%s\narch=%s\n' "$(value_or_unknown uname -s)" "$(value_or_unknown uname -r)" "$(value_or_unknown uname -m)"
  printf 'cpu_model=%s\nlogical_cpu_count=%s\ncores_per_socket=%s\nsockets=%s\n' "$(lscpu_field 'Model name')" "$(value_or_unknown getconf _NPROCESSORS_ONLN)" "$(lscpu_field 'Core(s) per socket')" "$(lscpu_field 'Socket(s)')"
  printf 'installed_memory_kib=%s\n' "$(awk '/^MemTotal:/ {print $2; found=1; exit} END {if (!found) print "unknown"}' /proc/meminfo 2>/dev/null || printf 'unknown')"
  printf 'virtualization_available=%s\nvirtualization_value=%s\ncontainer=%s\n' "$(test "$virtualization" = unknown && printf unknown || printf available)" "$virtualization" "$container"
  printf 'power_frequency_control=%s\ncache_control=untimed_preflight_warms_code_and_fixture_pages; no cache flush or pinning\n' "$power_control"
  printf 'network_control=IPv4_loopback_only; hardened client disables proxy discovery/features; no external network\n'
} > "$staging/environment.txt"
if grep -Ev '^[a-z0-9_]+=.*$' "$staging/environment.txt"; then
  printf 'invalid environment metadata line\n' >&2
  exit 1
fi
printf '%s  %s\n%s  %s\n' "$manifest_digest" "$manifest" "$capture_fixture_digest" "$capture_fixture" > "$staging/fixture-inputs.sha256"
command=(cargo bench --jobs 1 -p yosoi-benchmarks --bench criterion_capture -- --warm-up-time 1 --measurement-time 2 --sample-size 10 --noplot)
printf '%q ' "${command[@]}" > "$staging/command.txt"; printf '\n' >> "$staging/command.txt"
printf 'CRITERION_HOME=<run-directory>/criterion-raw\n' > "$staging/run-settings.txt"
CRITERION_HOME="$(realpath "$staging")/criterion-raw" "${command[@]}" 2>&1 | tee "$staging/criterion-output.txt"

required=(sha256_only yosoi_consume_response_body_pipeline source_classification_character_decode capture_finalization_bundle_retained capture_finalization_bundle_unavailable canonical_web_capture_wire local_raw_wreq_construct_request_and_exact_body_consumption full_capture_direct_http_including_hardened_client_construction full_capture_redirect_chain)
for group in "${required[@]}"; do
  grep -Fq "$group" "$staging/criterion-output.txt"
  find "$staging/criterion-raw" -path "*/$group/*/new/estimates.json" -print -quit | grep -q .
done
test "$(awk -F= '$1=="source_snapshot_commit" {print $2}' "$staging/environment.txt")" = "$source_snapshot_commit"
test "$(awk -F= '$1=="jj_change_id" {print $2}' "$staging/environment.txt")" = "$jj_change_id"
test "$(awk 'NR == 1 {print $1}' "$staging/fixture-inputs.sha256")" = "$manifest_digest"
test "$(awk 'NR == 2 {print $1}' "$staging/fixture-inputs.sha256")" = "$capture_fixture_digest"
scripts/fixtures/generate-cas-307-fixtures.py --check
(cd benchmarks/fixtures/web-capture/v1 && sha256sum -c SHA256SUMS) > "$staging/fixture-check.txt"
(cd "$staging" && find criterion-raw -name estimates.json -path '*/new/*' | sort) > "$staging/group-estimates.txt"
while IFS= read -r estimate; do case "$estimate" in criterion-raw/*) ;; *) exit 1;; esac; test -f "$staging/$estimate"; done < "$staging/group-estimates.txt"
! grep -Fq '.cas-307-staging.' "$staging/group-estimates.txt"
{
  printf '# CAS-307 benchmark baseline\n\nAtomic runner output. Exploratory and machine-specific; no regression threshold is implied.\n\n'
  printf 'Settings: 1 s warm-up, 2 s measurement, 10 samples. Criterion time units and 95%% confidence intervals are recorded in each estimate below.\n\n'
  printf '## Environment\n```text\n'; cat "$staging/environment.txt"; printf '```\n\n## Fixture digests\n```text\n'; cat "$staging/fixture-inputs.sha256"; printf '```\n\n'
  printf '## Group IDs and raw estimate paths\n```text\n'; cat "$staging/group-estimates.txt"; printf '```\n\n## Criterion output\n```text\n'; cat "$staging/criterion-output.txt"; printf '```\n\n'
  printf '## Unavailable measurement classes\nAllocation count, allocated bytes, peak live heap, peak RSS, hardware instructions, and modeled Callgrind instructions were not collected; no values or thresholds are inferred. Filesystem sink is N/A.\n'
} > "$staging/baseline.md"
! grep -Fq '.cas-307-staging.' "$staging/baseline.md"
scripts/fixtures/normalize-benchmark-text.py "$staging"

scripts/benchmarks/publish-benchmark-result.sh "$staging" "$destination"
trap - EXIT INT TERM
scripts/benchmarks/summarize-benchmark-change.py "$(dirname "$destination")"
