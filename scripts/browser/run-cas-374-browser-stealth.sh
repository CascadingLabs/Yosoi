#!/usr/bin/env bash
# CAS-374 exact-baseline browser fingerprint matrix. All cells run serially.
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
certified_base=yosoi-cas333:local
expected_base_id=sha256:90ef59e3973300ec7c0ef8d3d8d0ca7f791ca6cc485a34ce2f13041c001137fd
image=yosoi-cas374:local
destination=
reuse_image=0
declare -a live_urls=()

usage() {
  printf 'usage: %s [--reuse-image] [--live-suite substrate] [--live-url URL]... [destination]\n' "$0" >&2
}
while [ "$#" -gt 0 ]; do
  case "$1" in
    --live-url)
      [ "$#" -ge 2 ] || { usage; exit 64; }
      live_urls+=("$2")
      shift
      ;;
    --reuse-image) reuse_image=1 ;;
    --live-suite)
      [ "$#" -ge 2 ] || { usage; exit 64; }
      [ "$2" = substrate ] || { usage; exit 64; }
      live_urls+=(
        "https://abrahamjuliot.github.io/creepjs/"
        "https://deviceandbrowserinfo.com/are_you_a_bot"
        "https://bot.sannysoft.com/"
        "https://bot.incolumitas.com/"
      )
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    -*) usage; exit 64 ;;
    *)
      [ -z "$destination" ] || { usage; exit 64; }
      destination=$1
      ;;
  esac
  shift
done
destination=${destination:-$(scripts/benchmarks/benchmark-result-directory.sh browser)/cas-374-stealth}
max_swap_growth_mib=${CAS374_MAX_SWAP_GROWTH_MIB:-128}
if ! [[ "$max_swap_growth_mib" =~ ^[0-9]+$ ]] \
  || [ "$max_swap_growth_mib" -lt 128 ] \
  || [ "$max_swap_growth_mib" -gt 1024 ]; then
  printf '%s\n' 'CAS374_MAX_SWAP_GROWTH_MIB must be an integer from 128 through 1024' >&2
  exit 64
fi
max_swap_growth_kib=$((max_swap_growth_mib * 1024))
parent=$(dirname "$destination")
mkdir -p "$parent"
staging=$(mktemp -d "$parent/.cas-374-stealth.XXXXXX")
context=

read_pressure() {
  awk '
    /^MemAvailable:/ { available=$2 }
    /^SwapTotal:/ { swap_total=$2 }
    /^SwapFree:/ { swap_free=$2 }
    END { printf "%s %s\n", available, swap_total-swap_free }
  ' /proc/meminfo
}

read -r initial_available_kib initial_swap_used_kib < <(read_pressure)
resource_guard() {
  local available_kib swap_used_kib
  read -r available_kib swap_used_kib < <(read_pressure)
  if [ "$available_kib" -lt 8388608 ]; then
    printf 'CAS-374 stopped: host available memory fell below 8 GiB\n' >&2
    return 1
  fi
  if [ "$swap_used_kib" -gt 4194304 ] && [ "${CAS374_ALLOW_HIGH_BASELINE_SWAP:-0}" != 1 ]; then
    printf 'CAS-374 stopped: host swap usage exceeds 4 GiB\n' >&2
    return 1
  fi
  if [ "$swap_used_kib" -gt $((initial_swap_used_kib + max_swap_growth_kib)) ]; then
    printf 'CAS-374 stopped: host swap grew by more than %s MiB\n' "$max_swap_growth_mib" >&2
    return 1
  fi
}

cleanup() {
  status=$?
  trap - EXIT INT TERM
  if [ -n "$context" ] && [ -d "$context" ]; then
    rm -rf -- "$context"
  fi
  if [ "$status" -ne 0 ] && [ -d "$staging" ]; then
    failed="${destination}.failed.$$"
    mv -- "$staging" "$failed"
    printf 'CAS-374 diagnostics retained at %s\n' "$failed" >&2
  elif [ -d "$staging" ]; then
    rm -rf -- "$staging"
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM
if pgrep -x cargo >/dev/null || pgrep -x rustc >/dev/null || pgrep -x clippy-driver >/dev/null; then
  printf 'CAS-374 stopped: another Cargo, rustc, or Clippy process is active\n' >&2
  exit 1
fi
resource_guard

base_id=$(docker image inspect "$certified_base" --format '{{.Id}}')
[ "$base_id" = "$expected_base_id" ] || {
  printf 'CAS-374 requires certified CAS-373 image %s; tag resolves to %s\n' "$expected_base_id" "$base_id" >&2
  exit 1
}

context=$(mktemp -d "${TMPDIR:-/tmp}/cas374-container-context.XXXXXX")
scripts/browser/prepare-container-context.sh "$context" >/dev/null
source_hash=$(python3 - "$root" <<'PY'
import hashlib
import os
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
ignored = {
    ".git", ".jj", ".pi", ".agents", "target", "results", "node_modules",
    "coverage", "dist", "build", ".yosoi", ".voidcrawl", "keys", "secrets",
    ".ssh", ".aws",
}
digest = hashlib.sha256()
for current, directories, files in os.walk(root):
    directories[:] = sorted(name for name in directories if name not in ignored)
    for name in sorted(files):
        if name == ".env" or name.startswith(".env.") or name.endswith((
            ".key", ".pem", ".p12", ".pfx", ".crt", ".age", ".sops"
        )):
            continue
        path = pathlib.Path(current, name)
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        try:
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
        except FileNotFoundError:
            pass
print(digest.hexdigest())
PY
)

if [ "$reuse_image" -eq 1 ]; then
  image_source_hash=$(docker image inspect "$image" --format '{{index .Config.Labels "com.cascadinglabs.yosoi.cas374.source_sha256"}}')
  [ "$image_source_hash" = "$source_hash" ] || {
    printf '%s\n' 'CAS-374 refused stale image: source hash does not match the workspace' >&2
    exit 1
  }
  printf 'reused_image=%s\nsource_sha256=%s\n' "$image" "$source_hash" > "$staging/image-build.log"
else
  docker build --pull=false --tag "$image" \
    --label "com.cascadinglabs.yosoi.cas374.source_sha256=$source_hash" \
    --label "com.cascadinglabs.yosoi.cas374.base_image_id=$expected_base_id" \
    --file "$context/YosoiOxide/docker/browser-stealth/Dockerfile" "$context" \
    > "$staging/image-build.log"
  resource_guard
fi
image_id=$(docker image inspect "$image" --format '{{.Id}}')
actual_base_label=$(docker image inspect "$image" --format '{{index .Config.Labels "com.cascadinglabs.yosoi.cas374.base_image_id"}}')
[ "$actual_base_label" = "$expected_base_id" ] || { printf '%s\n' 'CAS-374 image lost its certified base identity' >&2; exit 1; }

chrome_version=$(docker run --rm --network none --read-only --user 10001:10001 --cap-drop ALL \
  --security-opt no-new-privileges:true --entrypoint /bin/cat "$image" \
  /usr/share/cas333/chromium-version.txt)
chrome_digest=$(docker run --rm --network none --read-only --user 10001:10001 --cap-drop ALL \
  --security-opt no-new-privileges:true --entrypoint /bin/cat "$image" \
  /usr/share/cas333/chromium-executable-sha256.txt)
probe_binary_size=$(docker run --rm --network none --read-only --user 10001:10001 --cap-drop ALL \
  --security-opt no-new-privileges:true --entrypoint /usr/bin/stat "$image" \
  -c %s /usr/local/bin/cas374-profile-browser-stealth)
probe_binary_sha256=$(docker run --rm --network none --read-only --user 10001:10001 --cap-drop ALL \
  --security-opt no-new-privileges:true --entrypoint /usr/bin/sha256sum "$image" \
  /usr/local/bin/cas374-profile-browser-stealth | awk '{print $1}')
[[ "$chrome_version" =~ ^Google\ Chrome\ 153\.0\.8010\.36[[:space:]]*$ ]] || {
  printf 'unexpected Chrome version: %q\n' "$chrome_version" >&2
  exit 1
}
[ "$chrome_digest" = ac7f9884974b551d29c89f24d0c697f373ce595a920ddafced441dd2554142db ] || {
  printf '%s\n' 'unexpected Chrome executable digest' >&2
  exit 1
}

jj_revision=$(jj log -r @ --no-graph -T 'commit_id ++ "\n"')
jj_change=$(jj log -r @ --no-graph -T 'change_id ++ "\n"')
controller_revision=$(sed -n 's/^`\([0-9a-f]\{40\}\)`.*$/\1/p' vendor/chromiumoxide/VENDORING.md | head -n 1)
cdp_revision=$(sed -n 's/.*Chromium revision:[[:space:]]*`\(r[0-9][0-9]*\)`.*/\1/p' vendor/chromiumoxide_cdp/VENDORING.md | head -n 1)
[ -n "$controller_revision" ] || { printf '%s\n' 'missing Chromiumoxide upstream revision' >&2; exit 1; }
[ -n "$cdp_revision" ] || { printf '%s\n' 'missing generated CDP revision' >&2; exit 1; }
cat > "$staging/identity.txt" <<EOF
schema=yosoi.cas374.identity.v1
captured_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
jj_change=$jj_change
jj_revision=$jj_revision
source_sha256=$source_hash
container_image=$image_id
container_base=$expected_base_id
chromium_version=$chrome_version
chromium_executable_sha256=$chrome_digest
chromiumoxide_upstream_revision=$controller_revision
generated_cdp_revision=$cdp_revision
generated_cdp_version=0.10.0-yosoi.m153.1
probe_binary_size_bytes=$probe_binary_size
probe_binary_sha256=$probe_binary_sha256
sandbox=required
site_process_isolation=chrome_default
live_checks=${#live_urls[@]}
high_baseline_swap_override=${CAS374_ALLOW_HIGH_BASELINE_SWAP:-0}
max_swap_growth_mib=$max_swap_growth_mib
EOF

container_run() {
  local network=$1 output=$2 mode=$3 policy=$4 cdp=$5
  shift 5
  local -a policy_args=(--webdriver-policy "$policy" --cdp-mode "$cdp")
  docker run --rm --user 10001:10001 --network "$network" --read-only \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,size=512m --shm-size=512m \
    --pids-limit=512 --memory=2g --memory-swap=2g --cpus=1 \
    --cap-drop ALL --security-opt no-new-privileges:true \
    --security-opt "seccomp=$root/docker/browser/seccomp-chrome.json" \
    --env CHROME_NO_SANDBOX=0 "$image" "$mode" \
    "${policy_args[@]}" "$@" \
    > "$output" 2> "${output%.json}.stderr.txt"
}

mkdir -p "$staging/hermetic" "$staging/live"
for mode in container-headless container-headful; do
  for cdp in normal minimal; do
    output="$staging/hermetic/${mode}-supported-configuration-${cdp}.json"
    container_run none "$output" "$mode" supported-configuration "$cdp"
    resource_guard
  done
  for policy in automation-disclosed bounded-disguise; do
    output="$staging/hermetic/${mode}-${policy}-normal.json"
    container_run none "$output" "$mode" "$policy" normal
    resource_guard
  done
done

for url in "${live_urls[@]}"; do
  site_hash=$(printf '%s' "$url" | sha256sum | cut -c1-12)
  for mode in container-headless container-headful; do
    for cdp in normal minimal; do
      output="$staging/live/${site_hash}-${mode}-${cdp}.json"
      container_run bridge "$output" "$mode" supported-configuration "$cdp" --live-url "$url"
      resource_guard
    done
  done
done

python3 - "$staging" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
hermetic = sorted((root / "hermetic").glob("*.json"))
if len(hermetic) != 8:
    raise SystemExit(f"CAS-374 expected 8 hermetic cells, found {len(hermetic)}")
for path in hermetic:
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("schema") != "yosoi.cas374.browser-stealth.v1":
        raise SystemExit(f"{path}: wrong schema")
    if record.get("browser_product") != "Chrome/153.0.8010.36":
        raise SystemExit(f"{path}: wrong browser product")
    if record.get("contract_passed") is not True or record.get("contract_violations"):
        raise SystemExit(f"{path}: hermetic contract failed")
    if len(record.get("stages", [])) != 6:
        raise SystemExit(f"{path}: incomplete lifecycle stages")
    stderr = path.with_suffix(".stderr.txt").read_text(encoding="utf-8")
    lowered = stderr.lower()
    if "unsupported command-line" in lowered or "unsupported flag" in lowered:
        raise SystemExit(f"{path}: unsupported command-line warning")
for path in sorted((root / "live").glob("*.json")):
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("browser_product") != "Chrome/153.0.8010.36" or not record.get("live"):
        raise SystemExit(f"{path}: incomplete live observation")
PY

cat > "$staging/README.md" <<'EOF'
# CAS-374 browser stealth evidence

The `hermetic/` matrix is the deterministic certification gate. The `live/`
records are passive third-party observations and are not bypass guarantees.
Exact source, controller, CDP, browser, image, sandbox, and isolation identities
are recorded in `identity.txt`; the image build log is retained separately.
EOF

scripts/benchmarks/publish-benchmark-result.sh "$staging" "$destination"
trap - EXIT INT TERM
printf 'CAS-374 evidence written to %s\n' "$destination"
