#!/usr/bin/env bash
# Build and run the CAS-383 profiler against a regular Stable container browser.
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
output=${1:-/tmp/cas383-oopif-container.jsonl}
image=${CAS383_IMAGE:-yosoi-cas383:local}
base=voidcrawl-headful:local
expected_base=sha256:9f89ca6fcbe3ed40f9c3847edaecf9de98b997e57dd65395a990916cd68dd82a
chrome_version=154.0.8037.57
chrome_package_sha256=66c0645f6a19871bab2844b8537c11a0db2e7d3bea8ef85a1c7cb52a54e65a3e

: "${CAS383_YOSOI_CHANGE:?CAS383_YOSOI_CHANGE is required}"
: "${CAS383_YOSOI_COMMIT:?CAS383_YOSOI_COMMIT is required}"
: "${CAS383_SOURCE_SHA256:?CAS383_SOURCE_SHA256 is required}"
: "${CAS383_CHROMIUMOXIDE_SHA256:?CAS383_CHROMIUMOXIDE_SHA256 is required}"

context=$(mktemp -d "${TMPDIR:-/tmp}/cas383-container-context.XXXXXX")
cleanup() { rm -rf "$context"; }
trap cleanup EXIT INT TERM

actual_base=$(docker image inspect "$base" --format '{{.Id}}')
if [ "$actual_base" != "$expected_base" ]; then
  printf 'CAS-383 base image mismatch: expected %s, got %s\n' "$expected_base" "$actual_base" >&2
  exit 1
fi

"$root/scripts/browser/prepare-container-context.sh" "$context" >/dev/null
docker build --pull=false --tag "$image" \
  --build-arg "CHROME_VERSION=$chrome_version" \
  --build-arg "CHROME_DEB_SHA256=$chrome_package_sha256" \
  --label "com.cascadinglabs.yosoi.cas383.source_sha256=$CAS383_SOURCE_SHA256" \
  --label "com.cascadinglabs.yosoi.cas383.chromiumoxide_sha256=$CAS383_CHROMIUMOXIDE_SHA256" \
  --label "com.cascadinglabs.yosoi.cas383.base_image_id=$expected_base" \
  --file "$context/docker/browser/Dockerfile" "$context"

mkdir -p "$(dirname "$output")"
docker run --rm \
  --user 10001:10001 \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=1g \
  --shm-size=1g \
  --pids-limit=2048 \
  --memory=4g \
  --memory-swap=4g \
  --cpus=2 \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --security-opt "seccomp=$root/docker/browser/seccomp-chrome.json" \
  --env CHROME_NO_SANDBOX=0 \
  --env "CAS383_ITERATIONS=${CAS383_ITERATIONS:-100}" \
  --env "CAS383_WARMUP=${CAS383_WARMUP:-10}" \
  --env "CAS383_YOSOI_CHANGE=$CAS383_YOSOI_CHANGE" \
  --env "CAS383_YOSOI_COMMIT=$CAS383_YOSOI_COMMIT" \
  --env "CAS383_SOURCE_SHA256=$CAS383_SOURCE_SHA256" \
  --env "CAS383_CHROMIUMOXIDE_SHA256=$CAS383_CHROMIUMOXIDE_SHA256" \
  "$image" cas383-oopif-headless > "$output"
