#!/usr/bin/env bash
# CAS-333 browser measurement classes. Do not start this unintentionally.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"

# Keep native evidence coupled to VoidCrawl's executable detection order. The
# canonical selection is supplied to each native browser command explicitly;
# no measurement relies on an inherited, implicit browser lookup.
resolve_chromium() {
  if test -n "${CHROME:-}" && test -e "$CHROME"; then
    printf '%s\n' "$CHROME"
    return 0
  fi
  local candidate name
  for name in chrome chrome-browser google-chrome-stable chromium chromium-browser msedge microsoft-edge microsoft-edge-stable; do
    candidate=$(command -v "$name" 2>/dev/null || true)
    if test -n "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  for candidate in /opt/chromium.org/chromium /opt/google/chrome /tmp/aws/lib; do
    if test -e "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  printf '%s\n' 'CAS-333: VoidCrawl chromiumoxide executable detection failed' >&2
  return 1
}

canonical_path() {
  local path=$1
  if command -v readlink >/dev/null 2>&1; then
    readlink -f -- "$path"
  else
    local directory filename
    directory=$(dirname -- "$path")
    filename=$(basename -- "$path")
    directory=$(cd -P "$directory" && pwd)
    printf '%s/%s\n' "$directory" "$filename"
  fi
}

# Hash every non-ignored file in the requested source tree. JJ snapshots
# eligible new files before listing them; the Git fallback lists tracked and
# untracked non-ignored files. This is deliberately not only a commit hash.
repository_source_hash() {
  local repository=$1 workspace_root prefix
  if workspace_root=$(jj -R "$root" root 2>/dev/null); then
    prefix=$(realpath --relative-to="$workspace_root" "$repository")
    test "$prefix" = . && prefix=""
    (
      cd "$workspace_root"
      jj file list ${prefix:+"$prefix"} |
        while IFS= read -r file; do sha256sum -- "$file"; done |
        sha256sum | awk '{print $1}'
    )
    return
  fi

  workspace_root=$(git -C "$repository" rev-parse --show-toplevel)
  prefix=$(realpath --relative-to="$workspace_root" "$repository")
  test "$prefix" = . && prefix=""
  test -z "$prefix" || prefix="$prefix/"
  (
    cd "$workspace_root"
    git ls-files -z -c -o --exclude-standard |
      while IFS= read -r -d '' file; do
        case "$file" in
          "$prefix"*) sha256sum -- "$file" ;;
        esac
      done |
      sha256sum | awk '{print $1}'
  )
}

manifest_package_value() {
  local manifest=$1 key=$2
  awk -F'"' -v key="$key" '$1 ~ "^" key "[[:space:]]*=" { print $2; exit }' "$manifest"
}

controller_upstream_revision() {
  sed -n 's/^`\([0-9a-f]\{40\}\)`.*$/\1/p' vendor/chromiumoxide/VENDORING.md | head -n 1
}

cdp_metadata_value() {
  local key=$1
  awk -F= -v key="$key" '$1 ~ "^" key "[[:space:]]*" { value=$2; gsub(/[ "\r]/, "", value); print value; exit }' vendor/chromiumoxide_cdp/Cargo.toml
}

source_identity() {
  local vcs status revision change source_hash
  if jj -R "$root" root >/dev/null 2>&1; then
    vcs=jj
    status=$(jj -R "$root" diff -r @ --summary)
    revision=$(jj -R "$root" log -r @ --no-graph -T 'commit_id')
    change=$(jj -R "$root" log -r @ --no-graph -T 'change_id')
  else
    vcs=git
    status=$(git -C "$root" status --porcelain=v1 --untracked-files=all)
    revision=$(git -C "$root" rev-parse HEAD)
    change=not_detected
  fi
  if test -n "$status"; then status=dirty; else status=clean; fi
  source_hash=$(repository_source_hash "$root")
  printf 'source_vcs=%s\nsource_snapshot_commit=%s\njj_change_id=%s\nsource_dirty=%s\nsource_sha256=%s\nsource_dirty_source_sha256=%s\n' \
    "$vcs" "$revision" "$change" "$status" "$source_hash" "$source_hash"
}

chromium_executable=$(canonical_path "$(resolve_chromium)")

chromium_identity() {
  local digest version
  digest=$(sha256sum -- "$chromium_executable" | awk '{print $1}')
  if ! version=$("$chromium_executable" --version 2>/dev/null) || test -z "$version"; then
    printf '%s\n' 'CAS-333: Chromium version could not be resolved' >&2
    return 1
  fi
  if [[ "$version" == *$'\n'* ]]; then
    printf '%s\n' 'CAS-333: Chromium version must be one line' >&2
    return 1
  fi
  if [[ "$version" == *"Chrome for Testing"* ]]; then
    printf '%s\n' 'CAS-333: testing-only Chrome distributions are prohibited' >&2
    return 1
  fi
  printf 'chromium_resolution=chromiumoxide_detection_order\nchromium_executable=%s\nchromium_sha256=%s\nchromium_version=%s\n' \
    "$chromium_executable" "$digest" "$version"
}

native_identity() {
  local controller_package controller_version controller_revision controller_hash
  local cdp_package cdp_version cdp_chrome_version cdp_chromium_revision cdp_v8_revision cdp_hash
  controller_package=$(manifest_package_value vendor/chromiumoxide/Cargo.toml name)
  controller_version=$(manifest_package_value vendor/chromiumoxide/Cargo.toml version)
  controller_revision=$(controller_upstream_revision)
  controller_hash=$(repository_source_hash "$root/vendor/chromiumoxide")
  cdp_package=$(manifest_package_value vendor/chromiumoxide_cdp/Cargo.toml name)
  cdp_version=$(manifest_package_value vendor/chromiumoxide_cdp/Cargo.toml version)
  cdp_chrome_version=$(cdp_metadata_value chrome-version)
  cdp_chromium_revision=$(cdp_metadata_value chromium-revision)
  cdp_v8_revision=$(cdp_metadata_value v8-revision)
  cdp_hash=$(repository_source_hash "$root/vendor/chromiumoxide_cdp")
  for value in "$controller_package" "$controller_version" "$controller_revision" "$cdp_package" "$cdp_version" "$cdp_chrome_version" "$cdp_chromium_revision" "$cdp_v8_revision"; do
    test -n "$value" || {
      printf '%s\n' 'CAS-333: controller or generated CDP identity could not be resolved' >&2
      return 1
    }
  done
  printf 'identity_schema=cas333.native-browser-identity.v1\n'
  source_identity
  printf 'controller_source=vendor/chromiumoxide\ncontroller_package=%s\ncontroller_version=%s\ncontroller_upstream_revision=%s\ncontroller_source_sha256=%s\n' \
    "$controller_package" "$controller_version" "$controller_revision" "$controller_hash"
  printf 'generated_cdp_source=vendor/chromiumoxide_cdp\ngenerated_cdp_package=%s\ngenerated_cdp_version=%s\ngenerated_cdp_chrome_version=%s\ngenerated_cdp_chromium_revision=r%s\ngenerated_cdp_v8_revision=%s\ngenerated_cdp_source_sha256=%s\n' \
    "$cdp_package" "$cdp_version" "$cdp_chrome_version" "$cdp_chromium_revision" "$cdp_v8_revision" "$cdp_hash"
  printf 'generated_cdp_pdl_manifest_sha256=%s\ngenerated_cdp_output_manifest_sha256=%s\ngenerated_cdp_output_sha256=%s\n' \
    "$(sha256sum vendor/chromiumoxide_cdp/PDL.SHA256 | awk '{print $1}')" \
    "$(sha256sum vendor/chromiumoxide_cdp/GENERATED.SHA256 | awk '{print $1}')" \
    "$(sha256sum vendor/chromiumoxide_cdp/src/cdp.rs | awk '{print $1}')"
  chromium_identity
}

record_command() {
  local output=$1
  shift
  printf '%q ' "$@" > "$output"
  printf '\n' >> "$output"
}

append_command() {
  local output=$1
  shift
  printf '%q ' "$@" >> "$output"
  printf '\n' >> "$output"
}

destination=${1:-$(scripts/benchmarks/benchmark-result-directory.sh browser)}
parent=$(dirname "$destination")
mkdir -p "$parent"
staging=$(mktemp -d "$parent/.cas-333-browser-staging.XXXXXX")
cleanup() {
  status=$?
  trap - EXIT INT TERM
  if test "$status" -ne 0 && test -d "$staging"; then
    failed="${destination}.failed.$$"
    mv -- "$staging" "$failed"
    staging=""
    printf 'CAS-333 browser diagnostics retained at %s\n' "$failed" >&2
  else
    rm -rf -- "$staging"
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
value_or_unknown() { local value; value=$("$@" 2>/dev/null || true); test -n "$value" && printf '%s' "$value" || printf unknown; }
measurement_identity=$(native_identity)
chromium_digest=$(printf '%s\n' "$measurement_identity" | awk -F= '/^chromium_sha256=/ {print $2}')
chromium_version=$(printf '%s\n' "$measurement_identity" | awk -F= '/^chromium_version=/ {print $2}')
container_change_id=$(printf '%s\n' "$measurement_identity" | awk -F= '/^jj_change_id=/ {print $2}')
test -n "$container_change_id" || { printf '%s\n' 'CAS-333: JJ change identity was empty' >&2; exit 1; }
xvfb_run=$(command -v xvfb-run) || { printf '%s\n' 'CAS-333: xvfb-run is required for isolated native headful certification' >&2; exit 1; }
xvfb_executable=$(command -v Xvfb) || { printf '%s\n' 'CAS-333: Xvfb is required for isolated native headful certification' >&2; exit 1; }
xvfb_run=$(canonical_path "$xvfb_run")
xvfb_executable=$(canonical_path "$xvfb_executable")
xvfb_screen='-screen 0 1920x1080x24'
manifest=benchmarks/fixtures/browser-capture/manifest.json
{
  printf 'captured_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '%s\n' "$measurement_identity"
  printf 'rustc=%s\ncargo=%s\n' "$(value_or_unknown rustc --version)" "$(value_or_unknown cargo --version)"
  printf 'target=%s\nos=%s\nkernel=%s\narch=%s\n' "$(rustc -vV 2>/dev/null | awk '/^host:/ {print $2}' || printf unknown)" "$(uname -s)" "$(uname -r)" "$(uname -m)"
  printf 'network_control=IPv4_loopback_only; container_network=none; no public URLs\nenvironments=native-headless,native-headful,container-headless,container-headful; DISPLAY_configured=%s; WAYLAND_DISPLAY_configured=%s\n' "${DISPLAY:+yes}" "${WAYLAND_DISPLAY:+yes}"
  printf 'native_headful_display=Xvfb; session_type=x11; screen=1920x1080x24\nxvfb_run=%s\nxvfb_run_sha256=%s\nxvfb_executable=%s\nxvfb_executable_sha256=%s\n' \
    "$xvfb_run" "$(sha256sum "$xvfb_run" | awk '{print $1}')" \
    "$xvfb_executable" "$(sha256sum "$xvfb_executable" | awk '{print $1}')"
  printf 'measurement_order=Criterion native modes; Divan allocation; native process matrices; container cgroup-v2 matrices\n'
} > "$staging/environment.txt"
sha256sum "$manifest" benchmarks/fixtures/browser-capture/minimal.html benchmarks/fixtures/browser-capture/full.html benchmarks/fixtures/browser-capture/growth.html crates/yosoi-web-capture/Cargo.toml Cargo.lock > "$staging/fixture-inputs.sha256"
mkdir -p "$staging/criterion-raw"
: > "$staging/criterion-command.txt"
: > "$staging/criterion-output.txt"
for mode in native-headless native-headful; do
  for artifact_set in minimal full growth; do
    criterion_command=(env "CHROME=$chromium_executable" "CAS333_CHROMIUM_SHA256=$chromium_digest" "CAS333_CHROMIUM_VERSION=$chromium_version" "CAS333_BROWSER_MODE=$mode" "CAS333_ARTIFACT_SET=$artifact_set" cargo bench -p yosoi-benchmarks --bench criterion_browser -- --warm-up-time 1 --measurement-time 2 --sample-size 10 --noplot)
    if test "$mode" = native-headful; then
      criterion_command=(env -u WAYLAND_DISPLAY XDG_SESSION_TYPE=x11 "$xvfb_run" -a -s "$xvfb_screen" "${criterion_command[@]}")
    fi
    append_command "$staging/criterion-command.txt" "${criterion_command[@]}"
    rm -rf target/criterion/browser_acquisition
    mode_output="$staging/criterion-$mode-$artifact_set-output.txt"
    "${criterion_command[@]}" > >(tee -a "$staging/criterion-output.txt" "$mode_output") 2>&1
    raw_directory="$staging/criterion-raw/$mode/$artifact_set"
    mkdir -p "$raw_directory"
    cp -R target/criterion/browser_acquisition "$raw_directory/browser_acquisition"
  done
done
divan_command=(cargo bench -p yosoi-benchmarks --bench allocation_browser -- --sample-count 100 --sample-size 1 --color never)
record_command "$staging/allocation-command.txt" "${divan_command[@]}"
"${divan_command[@]}" > >(tee "$staging/allocation-output.txt") 2>&1
native_artifact_set=${CAS333_NATIVE_ARTIFACT_SET:-full}
for mode in native-headless native-headful; do
  command=(env "CHROME=$chromium_executable" "CAS333_CHROMIUM_SHA256=$chromium_digest" "CAS333_CHROMIUM_VERSION=$chromium_version" CAS333_MODE="$mode" CAS333_ARTIFACT_SET="$native_artifact_set" scripts/browser/run-cas-333-soak.sh "$staging/$mode")
  if test "$mode" = native-headful; then
    command=(env -u WAYLAND_DISPLAY XDG_SESSION_TYPE=x11 "$xvfb_run" -a -s "$xvfb_screen" "${command[@]}")
  fi
  record_command "$staging/$mode-command.txt" "${command[@]}"
  "${command[@]}" > >(tee "$staging/$mode-output.txt") 2>&1
done
container_iterations=${CAS333_CONTAINER_ITERATIONS:-${CAS333_SOAK_ITERATIONS:-5}}
container_artifact_set=${CAS333_CONTAINER_ARTIFACT_SET:-full}
container_deadline_ms=${CAS333_CONTAINER_DEADLINE_MS:-15000}
container_terminal_deadline_ms=${CAS333_CONTAINER_TERMINAL_DEADLINE_MS:-${CAS333_SOAK_TERMINAL_DEADLINE_MS:-5000}}
command=(env "CAS333_CHANGE_ID=$container_change_id" scripts/browser/run-container-matrix.sh --environment container-headless --destination "$staging/container-headless" --iterations "$container_iterations" --deadline-ms "$container_deadline_ms" --terminal-deadline-ms "$container_terminal_deadline_ms" --artifact-set "$container_artifact_set")
record_command "$staging/container-headless-command.txt" "${command[@]}"
"${command[@]}" > >(tee "$staging/container-headless-output.txt") 2>&1
command=(env CAS333_CONTAINER_REUSE_IMAGE=1 "CAS333_CHANGE_ID=$container_change_id" scripts/browser/run-container-matrix.sh --environment container-headful --destination "$staging/container-headful" --iterations "$container_iterations" --deadline-ms "$container_deadline_ms" --terminal-deadline-ms "$container_terminal_deadline_ms" --artifact-set "$container_artifact_set")
record_command "$staging/container-headful-command.txt" "${command[@]}"
"${command[@]}" > >(tee "$staging/container-headful-output.txt") 2>&1
{
  printf '# CAS-333 browser benchmark baseline\n\nAtomic, local browser measurement evidence; no performance threshold is implied.\n\n'
  printf '## Environment\n```text\n'; cat "$staging/environment.txt"; printf '```\n\n## Fixture and provider input hashes\n```text\n'; cat "$staging/fixture-inputs.sha256"; printf '```\n\n'
  printf 'Exact commands and raw outputs are retained in `*-command.txt`, `*-output.txt`, `criterion-raw/`, and four environment-specific matrix directories.\n'
} > "$staging/baseline.md"
if test "$measurement_identity" != "$(native_identity)"; then
  printf '%s\n' 'CAS-333: refusing publication because source, controller, generated CDP, or Chromium identity changed during measurement' >&2
  exit 1
fi
scripts/benchmarks/publish-benchmark-result.sh "$staging" "$destination"
trap - EXIT INT TERM
scripts/benchmarks/summarize-benchmark-change.py "$(dirname "$destination")"
printf 'CAS-333 browser measurements written atomically to %s\n' "$destination"
