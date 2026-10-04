#!/usr/bin/env bash
# CAS-352 loopback-only warm browser capacity and Criterion evidence. Run sequentially.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"

mode=combined
case "${1:-}" in
  --identity-only) mode=identity-only; shift ;;
  --criterion-only) mode=criterion-only; shift ;;
  --finalize) mode=finalize; shift ;;
esac
if test "$#" -gt 1; then
  printf '%s\n' 'usage: run-cas-352-browser-execution.sh [--identity-only|--criterion-only|--finalize] [destination]' >&2
  exit 2
fi
destination=${1:-$(scripts/benchmarks/benchmark-result-directory.sh browser)/cas-352-execution}

# Keep identity capture coupled to the provider's executable detection order. The
# selected canonical path is supplied to every measurement command explicitly;
# no command relies on a CHROME export from its parent shell.
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
  printf '%s\n' 'CAS-352: VoidCrawl chromiumoxide executable detection failed' >&2
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

# Hash every non-ignored repository file, including untracked source. This is
# intentionally not a HEAD hash: dirty work must never masquerade as its HEAD.
repository_source_hash() {
  local repository=$1 workspace_root prefix
  if workspace_root=$(jj -R "$yosoi_repository" root 2>/dev/null); then
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

repository_identity() {
  local label=$1 repository=$2 status revision change source_hash prefix
  if jj -R "$yosoi_repository" root >/dev/null 2>&1; then
    prefix=$(realpath --relative-to="$yosoi_repository" "$repository")
    status=$(jj -R "$yosoi_repository" diff -r @ --summary -- "$prefix")
    revision=$(jj -R "$yosoi_repository" log -r @ --no-graph -T 'commit_id')
    change=$(jj -R "$yosoi_repository" log -r @ --no-graph -T 'change_id')
  else
    status=$(git -C "$repository" status --porcelain=v1 --untracked-files=all)
    revision=$(git -C "$repository" rev-parse HEAD)
    change=not_detected
  fi
  if test -n "$status"; then status=dirty; else status=clean; fi
  source_hash=$(repository_source_hash "$repository")
  printf '%s_repository=%s\n%s_revision=%s\n%s_change=%s\n%s_dirty=%s\n%s_source_sha256=%s\n%s_dirty_source_sha256=%s\n' \
    "$label" "$repository" "$label" "$revision" "$label" "$change" "$label" "$status" "$label" "$source_hash" "$label" "$source_hash"
}

yosoi_repository=${CAS352_YOSOI_ROOT:-$root}
voidcrawl_repository="$yosoi_repository/crates/voidcrawl"
chromium_executable=$(canonical_path "$(resolve_chromium)")

chromium_metadata() {
  local chromium_digest chromium_version
  chromium_digest=$(sha256sum -- "$chromium_executable" | awk '{print $1}')
  if ! chromium_version=$("$chromium_executable" --version 2>/dev/null) || test -z "$chromium_version"; then
    printf '%s\n' 'CAS-352: Chromium version could not be resolved' >&2
    return 1
  fi
  if [[ "$chromium_version" == *$'\n'* ]]; then
    printf '%s\n' 'CAS-352: Chromium version must be one line' >&2
    return 1
  fi
  if [[ "$chromium_version" == *"Chrome for Testing"* ]]; then
    printf '%s\n' 'CAS-352: testing-only Chrome distributions are prohibited' >&2
    return 1
  fi
  printf 'chromium_resolution=chromiumoxide_detection_order\nchromium_executable=%s\nchromium_sha256=%s\nchromium_version=%s\n' \
    "$chromium_executable" "$chromium_digest" "$chromium_version"
}

identity_metadata() {
  local controller_version controller_source_hash
  test -f "$yosoi_repository/vendor/chromiumoxide/Cargo.toml" || {
    printf '%s\n' 'CAS-352: chromiumoxide controller manifest could not be resolved' >&2
    return 1
  }
  controller_version=$(awk -F'"' '$1 ~ /^version[[:space:]]*=/ { print $2; exit }' "$yosoi_repository/vendor/chromiumoxide/Cargo.toml")
  test -n "$controller_version" || {
    printf '%s\n' 'CAS-352: chromiumoxide controller version could not be resolved' >&2
    return 1
  }
  controller_source_hash=$(repository_source_hash "$yosoi_repository/vendor/chromiumoxide")
  repository_identity yosoi "$yosoi_repository"
  repository_identity voidcrawl "$voidcrawl_repository"
  printf 'controller_crate=chromiumoxide\ncontroller_version=%s\ncontroller_source_sha256=%s\ncontroller_dirty_source_sha256=%s\n' \
    "$controller_version" "$controller_source_hash" "$controller_source_hash"
  chromium_metadata
}

metadata_value() {
  local metadata=$1 key=$2
  grep -m 1 -F "${key}=" "$metadata" | cut -d= -f2-
}

metadata_matches_current_identity() {
  local metadata=$1 line current
  test -f "$metadata" || {
    printf 'CAS-352: missing metadata at %s\n' "$metadata" >&2
    return 1
  }
  current=$(identity_metadata)
  while IFS= read -r line; do
    test -z "$line" && continue
    if ! grep -Fqx -- "$line" "$metadata"; then
      printf 'CAS-352: evidence identity is stale or does not match the current source/runtime: %s\n' "$line" >&2
      return 1
    fi
  done <<<"$current"
}

record_command() {
  local output=$1
  shift
  printf '%q ' "$@" > "$output"
  printf '\n' >> "$output"
}

command_binds_chromium_identity() {
  local command_file=$1
  local metadata=$2
  python3 - "$command_file" \
    "$(metadata_value "$metadata" chromium_executable)" \
    "$(metadata_value "$metadata" chromium_sha256)" \
    "$(metadata_value "$metadata" chromium_version)" <<'PY'
import shlex
import sys

command_file, executable, digest, version = sys.argv[1:]
tokens = shlex.split(open(command_file, encoding="utf-8").read())
required = {
    f"CHROME={executable}",
    f"CAS352_CHROMIUM_SHA256={digest}",
    f"CAS352_CHROMIUM_VERSION={version}",
}
if not tokens or tokens[0] != "env" or not required.issubset(tokens):
    raise SystemExit(f"CAS-352: {command_file} does not bind the recorded Chromium identity")
PY
}

validate_criterion_evidence() {
  local directory=$1 metadata=$2 file
  for file in criterion-command.txt criterion-output.txt criterion-warm-command.txt criterion-warm-output.txt; do
    test -s "$directory/$file" || {
      printf 'CAS-352: missing Criterion command or output evidence: %s\n' "$directory/$file" >&2
      return 1
    }
  done
  command_binds_chromium_identity "$directory/criterion-command.txt" "$metadata"
  command_binds_chromium_identity "$directory/criterion-warm-command.txt" "$metadata"
}

validate_soak_matrix() {
  local attempts=$1 iterations=$2 concurrency=$3
  python3 - "$attempts" "$iterations" "$concurrency" <<'PY'
import json
import sys

path, iterations_text, concurrency_text = sys.argv[1:]
iterations = int(iterations_text)
concurrency = int(concurrency_text)
with open(path, encoding="utf-8") as source:
    records = [json.loads(line) for line in source if line.strip()]
attempts = [record for record in records if record.get("record") == "attempt"]
summaries = [record for record in records if record.get("record") == "summary"]
expected = iterations * concurrency
if len(records) != expected + 1 or len(attempts) != expected or len(summaries) != 1:
    raise SystemExit(f"CAS-352: {path} must contain {expected} attempts and one summary")
summary = summaries[0]
if (summary.get("iterations") != iterations
        or summary.get("concurrency") != concurrency
        or summary.get("attempts") != expected):
    raise SystemExit(f"CAS-352: {path} summary does not match iterations × concurrency")
PY
}

validate_soak_evidence() {
  local directory=$1 metadata=$2 label concurrency file
  local iterations
  iterations=$(metadata_value "$metadata" soak_iterations)
  case "$iterations" in
    ''|*[!0-9]*) printf '%s\n' 'CAS-352: soak metadata has no valid iteration count' >&2; return 1 ;;
  esac
  for label in one-by-one one-by-two two-by-four; do
    case "$label" in
      one-by-one) concurrency=1 ;;
      one-by-two) concurrency=2 ;;
      two-by-four) concurrency=4 ;;
    esac
    for file in attempts.jsonl command.txt process-tree.json process-tree.csv status.txt; do
      test -s "$directory/$label/$file" || {
        printf 'CAS-352: missing soak evidence: %s\n' "$directory/$label/$file" >&2
        return 1
      }
    done
    test "$(cat "$directory/$label/status.txt")" = 0 || {
      printf 'CAS-352: soak matrix %s did not succeed\n' "$label" >&2
      return 1
    }
    command_binds_chromium_identity "$directory/$label/command.txt" "$metadata"
    validate_soak_matrix "$directory/$label/attempts.jsonl" "$iterations" "$concurrency"
  done
}

write_evidence_hashes() {
  local directory=$1 scope=$2
  (
    cd "$directory"
    sha256sum metadata.txt criterion-command.txt criterion-output.txt criterion-warm-command.txt criterion-warm-output.txt > criterion-evidence.sha256
    if test "$scope" = combined; then
      sha256sum \
        metadata.txt fixture-provider-inputs.sha256 build-command.txt \
        criterion-command.txt criterion-output.txt criterion-warm-command.txt criterion-warm-output.txt \
        one-by-one/attempts.jsonl one-by-one/command.txt one-by-one/process-tree.json one-by-one/process-tree.csv one-by-one/status.txt \
        one-by-two/attempts.jsonl one-by-two/command.txt one-by-two/process-tree.json one-by-two/process-tree.csv one-by-two/status.txt \
        two-by-four/attempts.jsonl two-by-four/command.txt two-by-four/process-tree.json two-by-four/process-tree.csv two-by-four/status.txt \
        > evidence.sha256
    fi
  )
}

finalize_existing_evidence() {
  local directory=$1 scope
  local metadata="$directory/metadata.txt"
  metadata_matches_current_identity "$metadata"
  scope=$(metadata_value "$metadata" evidence_scope)
  case "$scope" in
    criterion-only|combined) ;;
    *) printf 'CAS-352: unsupported evidence scope in %s\n' "$metadata" >&2; return 1 ;;
  esac
  validate_criterion_evidence "$directory" "$metadata"
  if test "$scope" = combined; then
    validate_soak_evidence "$directory" "$metadata"
  fi
  write_evidence_hashes "$directory" "$scope"
}

write_metadata() {
  local directory=$1 scope=$2 iterations=${3:-}
  {
    printf 'captured_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    identity_metadata
    printf 'evidence_scope=%s\n' "$scope"
    printf 'network_control=IPv4 loopback only; public URLs forbidden\n'
    printf 'criterion_mode=native-headless; cold_and_warm_fresh_context=true\n'
    if test "$scope" = combined; then
      printf 'mode=warm-process-fresh-context; matrices=1x1@1,1x2@2,2x4@4; iterations=%s; recycle_threshold=100\n' "$iterations"
      printf 'soak_iterations=%s\n' "$iterations"
      printf 'metrics=attempt_elapsed_micros,process_generation,process_count,rss_kib,pss_kib,cpu_ticks,fd_count,tasks,role_counts,residual_capacity,remaining_pids,orphan_pids\n'
      printf 'sample_interval_ms=%s; cleanup_grace_ms=%s\n' "$sample_ms" "$cleanup_grace_ms"
    fi
    printf 'rustc=%s\ncargo=%s\n' "$(rustc --version)" "$(cargo --version)"
  } > "$directory/metadata.txt"
}

run_criterion_measurements() {
  local directory=$1
  local digest version
  digest=$(chromium_metadata | awk -F= '/^chromium_sha256=/ {print $2}')
  version=$(chromium_metadata | awk -F= '/^chromium_version=/ {print $2}')
  local cold_command=(env "CHROME=$chromium_executable" "CAS352_CHROMIUM_SHA256=$digest" "CAS352_CHROMIUM_VERSION=$version" CAS333_BROWSER_MODE=native-headless CAS333_ARTIFACT_SET=all cargo bench -p yosoi-benchmarks --bench criterion_browser -- cold_process_capture_to_staged_facts --warm-up-time 1 --measurement-time 2 --sample-size 10 --noplot)
  record_command "$directory/criterion-command.txt" "${cold_command[@]}"
  "${cold_command[@]}" > "$directory/criterion-output.txt" 2>&1
  local warm_command=(env "CHROME=$chromium_executable" "CAS352_CHROMIUM_SHA256=$digest" "CAS352_CHROMIUM_VERSION=$version" CAS333_BROWSER_MODE=native-headless CAS333_ARTIFACT_SET=all cargo bench -p yosoi-benchmarks --bench criterion_browser -- warm_process_fresh_context_capture_to_staged_facts --warm-up-time 1 --measurement-time 2 --sample-size 10 --noplot)
  record_command "$directory/criterion-warm-command.txt" "${warm_command[@]}"
  "${warm_command[@]}" > "$directory/criterion-warm-output.txt" 2>&1
}

run_soak_measurements() {
  local directory=$1
  local digest version label processes contexts_total contexts_per_process tabs_total concurrency output controller sampler status
  digest=$(chromium_metadata | awk -F= '/^chromium_sha256=/ {print $2}')
  version=$(chromium_metadata | awk -F= '/^chromium_version=/ {print $2}')
  cargo build --release -p yosoi-benchmarks --bin profile_browser_execution
  printf '%s\n' 'cargo build --release -p yosoi-benchmarks --bin profile_browser_execution' > "$directory/build-command.txt"

  # label:processes:contexts_total:contexts_per_process:tabs_total:concurrency
  local matrices=(
    one-by-one:1:1:1:1:1
    one-by-two:1:2:2:2:2
    two-by-four:2:4:2:4:4
  )
  for matrix in "${matrices[@]}"; do
    IFS=: read -r label processes contexts_total contexts_per_process tabs_total concurrency <<<"$matrix"
    output="$directory/$label"
    mkdir -p "$output"
    local command=(env "CHROME=$chromium_executable" "CAS352_CHROMIUM_SHA256=$digest" "CAS352_CHROMIUM_VERSION=$version" target/release/profile_browser_execution
      --iterations "$iterations"
      --concurrency "$concurrency"
      --processes "$processes"
      --contexts-total "$contexts_total"
      --contexts-per-process "$contexts_per_process"
      --tabs-total "$tabs_total"
      --queue-depth 8
      --recycle-threshold 100)
    record_command "$output/command.txt" "${command[@]}"
    "${command[@]}" > "$output/attempts.jsonl" &
    controller=$!
    python3 scripts/browser/sample_process_tree.py \
      --pid "$controller" \
      --interval-ms "$sample_ms" \
      --cleanup-grace-ms "$cleanup_grace_ms" \
      --output "$output/process-tree.json" \
      --csv "$output/process-tree.csv" &
    sampler=$!
    set +e
    wait "$controller"; status=$?
    set -e
    wait "$sampler"
    printf '%s\n' "$status" > "$output/status.txt"
    if test "$status" -ne 0; then
      return "$status"
    fi
  done
  sha256sum \
    benchmarks/fixtures/browser-capture/manifest.json \
    benchmarks/fixtures/browser-capture/minimal.html \
        crates/yosoi-web-capture/Cargo.toml \
    Cargo.lock > "$directory/fixture-provider-inputs.sha256"
}

if test "$mode" = identity-only; then
  mkdir -p -- "$destination"
  identity_metadata | tee "$destination/metadata.txt"
  exit 0
fi

if test "$mode" = finalize; then
  finalize_existing_evidence "$destination"
  printf 'CAS-352 browser evidence finalized at %s\n' "$destination"
  exit 0
fi

parent=$(dirname "$destination")
mkdir -p "$parent"
staging=$(mktemp -d "$parent/.cas-352-browser-staging.XXXXXX")
cleanup() {
  status=$?
  trap - EXIT INT TERM
  rm -rf -- "$staging"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Capture the identity before work starts, then finalization recomputes it and
# rejects any source or runtime drift that occurred while collecting evidence.
measurement_identity=$(identity_metadata)
iterations=${CAS352_SOAK_ITERATIONS:-25}
sample_ms=${CAS352_SAMPLE_MS:-100}
cleanup_grace_ms=${CAS352_CLEANUP_GRACE_MS:-5000}

run_criterion_measurements "$staging"
if test "$mode" = combined; then
  run_soak_measurements "$staging"
fi

if test "$measurement_identity" != "$(identity_metadata)"; then
  printf '%s\n' 'CAS-352: refusing finalization because source or Chromium identity changed during measurement' >&2
  exit 1
fi
write_metadata "$staging" "$mode" "$iterations"
finalize_existing_evidence "$staging"
{
  printf '# CAS-352 browser execution evidence\n\n'
  printf 'Local loopback-only evidence is final only after metadata, commands, outputs, and hashes pass finalization for the current source/runtime identity.\n'
  printf 'No universal performance threshold is implied.\n'
} > "$staging/README.md"

scripts/benchmarks/publish-benchmark-result.sh "$staging" "$destination"
trap - EXIT INT TERM
printf 'CAS-352 browser execution evidence written atomically to %s\n' "$destination"
