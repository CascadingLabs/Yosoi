#!/usr/bin/env bash
# Run a compiled workspace test in the existing Yosoi browser image.
set -euo pipefail
task_root=$(cd -- "$(dirname -- "$0")/../.." && pwd)
task_binary=${1:?usage: run-container.sh /absolute/test-binary /absolute/evidence-dir [test arguments]}
task_evidence=${2:?an evidence directory is required}
shift 2
task_image=${YOSOI_SPIKE_IMAGE:-yosoi-cas333:local}
task_image_id=$(docker image inspect "$task_image" --format '{{.Id}}')
task_revision=${YOSOI_SPIKE_SOURCE_REVISION:-$(jj -R "$task_root" log -r @ --no-graph -T commit_id)}
mkdir -p -- "$task_evidence"
# This fresh fixture-only output directory contains no source or credentials.
chmod a+rwx -- "$task_evidence"
printf 'image=%s source=%s binary=%s\n' "$task_image_id" "$task_revision" "$task_binary"
docker run --rm --init --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --security-opt "seccomp=$task_root/docker/browser/seccomp-chrome.json" \
  --user 10001:10001 --cpus 1 --memory 2g --memory-swap 2g --pids-limit 512 \
  --shm-size 256m --tmpfs /tmp:rw,nosuid,nodev,size=768m,mode=1777 \
  --mount "type=bind,src=$task_binary,dst=/spike/sdk-tests,readonly" \
  --mount "type=bind,src=$task_root/spikes/browser-automation/container-profile.sh,dst=/usr/local/bin/cas333-profile-browser,readonly" \
  --mount "type=bind,src=$task_root/spikes/browser-automation/fixtures,dst=$task_root/spikes/browser-automation/fixtures,readonly" \
  --mount "type=bind,src=$task_evidence,dst=/evidence" \
  --env CHROME_NO_SANDBOX=0 --env YOSOI_BROWSER_TESTS=1 \
  --env YOSOI_BROWSER_OUTPUT_DIR=/evidence \
  --env "YOSOI_SPIKE_SOURCE_REVISION=$task_revision" \
  --env "YOSOI_SPIKE_BROWSER_IDENTITY=Chrome-153.0.8010.36;image=$task_image_id" \
  "$task_image_id" container-headless "$@"
