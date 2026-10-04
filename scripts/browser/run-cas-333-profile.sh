#!/usr/bin/env bash
# Bounded CAS-333 controller plus Chromium process-tree profile; loopback targets only.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
destination=${1:-$(scripts/benchmarks/benchmark-result-directory.sh process)/cas-333-browser}
shift || true
workload="${CAS333_WORKLOAD:-}"
mode="${CAS333_MODE:-native-headless}"
artifact_set="${CAS333_ARTIFACT_SET:-minimal}"
while (($#)); do
  case "$1" in
    --workload) workload=${2:?missing workload}; shift 2 ;;
    --mode) mode=${2:?missing mode}; shift 2 ;;
    --artifact-set) artifact_set=${2:?missing artifact set}; shift 2 ;;
    *) printf 'usage: %s [destination] --workload success|cancellation|deadline|failure [--mode native-headless|native-headful] [--artifact-set minimal|full|growth]\n' "$0" >&2; exit 2 ;;
  esac
done
case "$workload" in success|cancellation|deadline|failure) ;; *) printf '%s\n' 'a single --workload is required (success cancellation deadline failure)' >&2; exit 2 ;; esac
case "$mode" in native-headless|native-headful) ;; *) printf '%s\n' 'mode must be native-headless or native-headful' >&2; exit 2 ;; esac
case "$artifact_set" in minimal|full|growth) ;; *) printf '%s\n' 'artifact set must be minimal, full, or growth' >&2; exit 2 ;; esac
iterations=${CAS333_ITERATIONS:-2}
deadline_ms=${CAS333_DEADLINE_MS:-5000}
sample_ms=${CAS333_SAMPLE_MS:-100}
cleanup_grace_ms=${CAS333_CLEANUP_GRACE_MS:-2000}
concurrency=${CAS333_CONCURRENCY:-1}
parent=$(dirname "$destination")
mkdir -p "$parent"
staging=$(mktemp -d "$parent/.cas-333-staging.XXXXXX")
backup=""
cleanup() { status=$?; trap - EXIT INT TERM; rm -rf -- "$staging"; if test -n "$backup" && test -e "$backup" && ! test -e "$destination"; then mv -- "$backup" "$destination"; fi; exit "$status"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
value_or_unknown() { local value; value=$("$@" 2>/dev/null || true); test -n "$value" && printf '%s' "$value" || printf unknown; }
resolve_chromium() {
  local name
  if test -n "${CHROME:-}"; then
    test -x "$CHROME" || { printf 'CAS-333: CHROME is not executable: %s\n' "$CHROME" >&2; return 1; }
    printf '%s\n' "$CHROME"
    return
  fi
  for name in google-chrome-stable google-chrome chromium chromium-browser chrome; do
    if command -v "$name" >/dev/null 2>&1; then
      command -v "$name"
      return
    fi
  done
  printf '%s\n' 'CAS-333: no Chromium executable found' >&2
  return 1
}
chromium_executable=$(realpath -- "$(resolve_chromium)")
chromium_sha256=$(sha256sum -- "$chromium_executable" | awk '{print $1}')
chromium_version=$("$chromium_executable" --version 2>/dev/null) || { printf '%s\n' 'CAS-333: Chromium version could not be resolved' >&2; exit 1; }
test -n "$chromium_version" || { printf '%s\n' 'CAS-333: Chromium version was empty' >&2; exit 1; }
if [[ "$chromium_version" == *$'\n'* ]]; then
  printf '%s\n' 'CAS-333: Chromium version must be one line' >&2
  exit 1
fi
if [[ "$chromium_version" == *"Chrome for Testing"* ]]; then
  printf '%s\n' 'CAS-333: testing-only Chrome distributions are prohibited' >&2
  exit 1
fi
if test -n "${CAS333_CHROMIUM_SHA256:-}" && test "$chromium_sha256" != "$CAS333_CHROMIUM_SHA256"; then
  printf '%s\n' 'CAS-333: selected Chromium digest does not match the orchestrator identity' >&2
  exit 1
fi
if test -n "${CAS333_CHROMIUM_VERSION:-}" && test "$chromium_version" != "$CAS333_CHROMIUM_VERSION"; then
  printf '%s\n' 'CAS-333: selected Chromium version does not match the orchestrator identity' >&2
  exit 1
fi
export CHROME="$chromium_executable"
source_snapshot_commit=$(jj log -r @ --no-graph -T 'commit_id' 2>/dev/null || git rev-parse HEAD)
jj_change_id=$(jj log -r @ --no-graph -T 'change_id' 2>/dev/null || printf not_detected)
cargo build --release -p yosoi-benchmarks --bin profile_browser
printf '%s\n' 'cargo build --release -p yosoi-benchmarks --bin profile_browser' > "$staging/build-command.txt"
target/release/profile_browser --mode "$mode" --artifact-set "$artifact_set" --workload "$workload" --iterations "$iterations" --concurrency "$concurrency" --deadline-ms "$deadline_ms" > "$staging/$workload.jsonl" &
controller=$!
python3 scripts/browser/sample_process_tree.py --pid "$controller" --interval-ms "$sample_ms" --cleanup-grace-ms "$cleanup_grace_ms" --output "$staging/$workload-tree.json" --csv "$staging/$workload-tree.csv" &
sampler=$!
set +e; wait "$controller"; status=$?; set -e
wait "$sampler"
printf '%s\n' "$status" > "$staging/$workload.status"
web_manifest=benchmarks/fixtures/web-capture/v1/manifest.json
browser_manifest=benchmarks/fixtures/browser-capture/manifest.json
capture_fixture=benchmarks/fixtures/web-capture/v1/complete-capture-v1.json
provider_manifest=crates/yosoi-web-capture/Cargo.toml
sha256sum "$web_manifest" "$browser_manifest" "$capture_fixture" "$provider_manifest" Cargo.lock > "$staging/fixture-provider-inputs.sha256"
{
  printf 'captured_utc=%s\nsource_snapshot_commit=%s\njj_change_id=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$source_snapshot_commit" "$jj_change_id"
  printf 'provider=yosoi-web-capture; adapter=capture_attempt; provider_manifest=%s\n' "$provider_manifest"
  printf 'source=CAS-333 generated loopback HTML; web_manifest=%s; browser_manifest=%s; capture_fixture=%s\n' "$web_manifest" "$browser_manifest" "$capture_fixture"
  printf 'network_control=IPv4 loopback only; failure workload declares a larger body then disconnects after a retained prefix\n'
  printf 'mode=%s; artifact_set=%s; workload=%s; iterations=%s; concurrency=%s; deadline_ms=%s; cancellation=after every concurrent attempt is accepted by delayed loopback\n' "$mode" "$artifact_set" "$workload" "$iterations" "$concurrency" "$deadline_ms"
  printf 'rustc=%s\ncargo=%s\n' "$(value_or_unknown rustc --version)" "$(value_or_unknown cargo --version)"
  printf 'target=%s\nos=%s\nkernel=%s\narch=%s\n' "$(rustc -vV 2>/dev/null | awk '/^host:/ {print $2}' || printf unknown)" "$(uname -s)" "$(uname -r)" "$(uname -m)"
  printf 'chromium_resolution=CHROME_first_then_detection_order\nchromium_executable=%s\nchromium_sha256=%s\nchromium_version=%s\n' \
    "$chromium_executable" "$chromium_sha256" "$chromium_version"
  printf 'environment=%s; viewport=provider-default; DISPLAY_configured=%s; WAYLAND_DISPLAY_configured=%s\n' "$mode" "${DISPLAY:+yes}" "${WAYLAND_DISPLAY:+yes}"
  printf 'process_scope=controller PID and recursively discovered descendants retained after controller exit; sample_interval_ms=%s; cleanup_grace_ms=%s; roles=controller,browser,renderer,gpu,utility,other\n' "$sample_ms" "$cleanup_grace_ms"
} > "$staging/metadata.txt"
python3 - "$mode" "$artifact_set" "$workload" "$status" "$staging/$workload.jsonl" "$staging/$workload-tree.json" > "$staging/summary.csv" <<'PY'
import csv, json, sys
mode, artifact_set, workload, status, records_path, tree_path = sys.argv[1:]
records = []
with open(records_path) as source:
    for line in source:
        if line.strip():
            records.append(json.loads(line))
with open(tree_path) as source:
    tree = json.load(source)
peak = tree["peak"]
cleanup = tree["cleanup"]
def quantile(values, percentile):
    if not values:
        return ""
    values = sorted(values)
    index = (len(values) - 1) * percentile / 100
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (index - lower)

elapsed = [record["elapsed_ms"] for record in records]
cancellation_to_return = [record["cancellation_to_return_ms"] for record in records if record["cancellation_to_return_ms"] is not None]
header = ["mode", "artifact_set", "workload", "status", "attempts", "finalization_failures", "elapsed_p50_ms", "elapsed_p95_ms", "elapsed_p99_ms", "cancellation_to_return_p50_ms", "cancellation_to_return_p95_ms", "cancellation_to_return_p99_ms", "peak_process_count", "peak_rss_kib", "peak_pss_kib", "peak_cpu_ticks", "peak_fd_count", "peak_task_count", "peak_controller_count", "peak_browser_count", "peak_renderer_count", "peak_gpu_count", "peak_utility_count", "peak_other_count", "cleanup_timed_out", "cleanup_remaining_count"]
row = [mode, artifact_set, workload, status, len(records), sum(record["finalization"] != "ok" for record in records), *(quantile(elapsed, value) for value in (50, 95, 99)), *(quantile(cancellation_to_return, value) for value in (50, 95, 99)), peak["process_count"]["value"]]
for name in ("rss_kib", "pss_kib", "cpu_ticks", "fd_count", "threads"):
    value = peak[name]["value"]
    row.append("" if value is None else value)
row.extend(peak["role_counts"][name] for name in ("controller", "browser", "renderer", "gpu", "utility", "other"))
row.extend((str(cleanup["timed_out"]).lower(), cleanup["remaining_count"]))
writer = csv.writer(sys.stdout)
writer.writerow(header)
writer.writerow(row)
PY
if test -e "$destination"; then backup="$parent/.cas-333-backup.$$"; mv "$destination" "$backup"; fi
mv "$staging" "$destination"; staging="$parent/.cas-333-complete.$$"
if test -n "$backup"; then rm -rf -- "$backup"; backup=""; fi
trap - EXIT INT TERM
printf 'CAS-333 raw profile written atomically to %s\n' "$destination"
if test "$status" -ne 0; then
  exit "$status"
fi
