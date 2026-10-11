#!/usr/bin/env bash
# One hardened, network-enabled runtime for tests and the live SDK comparison.
set -euo pipefail
task_root=$(cd -- "$(dirname -- "$0")/../.." && pwd)
task_binary=${1:?usage: run-yielding.sh /absolute/binary /absolute/output [arguments]}
task_output=${2:?an output directory is required}
shift 2
task_image=${YOSOI_YIELD_IMAGE:-yosoi-cas383:local}
task_mode=${YOSOI_YIELD_MODE:-headless}
case "$task_mode" in headless|headful) ;; *) printf '%s\n' 'mode must be headless or headful' >&2; exit 64;; esac
task_image_id=$(docker image inspect "$task_image" --format '{{.Id}}')
task_browser=$(docker run --rm --entrypoint /bin/cat "$task_image_id" /usr/share/cas333/chromium-version.txt)
task_revision=$(jj -R "$task_root" log -r @ --no-graph -T commit_id)
mkdir -p -- "$task_output"
chmod a+rwx -- "$task_output"
printf 'source=%s image=%s browser=%s mode=%s\n' "$task_revision" "$task_image_id" "$task_browser" "$task_mode" | tee "$task_output/run.log"
docker run --rm --init --network bridge --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --security-opt "seccomp=$task_root/docker/browser/seccomp-chrome.json" \
  --user 10001:10001 --cpus 1 --memory 3g --memory-swap 3g --pids-limit 1024 \
  --shm-size 256m --tmpfs /tmp:rw,nosuid,nodev,size=768m,mode=1777 \
  --mount "type=bind,src=$task_binary,dst=/spike/sdk-tests,readonly" \
  --mount "type=bind,src=$task_root/spikes/browser-automation/container-profile.sh,dst=/usr/local/bin/cas333-profile-browser,readonly" \
  --mount "type=bind,src=$task_root/spikes/browser-automation/fixtures,dst=$task_root/spikes/browser-automation/fixtures,readonly" \
  --mount "type=bind,src=$task_output,dst=/evidence" \
  --env CHROME_NO_SANDBOX=0 --env YOSOI_BROWSER_TESTS=1 \
  --env YOSOI_BROWSER_OUTPUT_DIR=/evidence --env "YOSOI_YIELD_MODE=$task_mode" \
  --env YOSOI_UNTIL_STRESS_ROUNDS \
  --env "YOSOI_SPIKE_SOURCE_REVISION=$task_revision" \
  --env "YOSOI_SPIKE_BROWSER_IDENTITY=$task_browser;image=$task_image_id" \
  "$task_image_id" "container-$task_mode" "$@" 2>&1 | tee -a "$task_output/run.log"
