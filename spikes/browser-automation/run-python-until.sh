#!/usr/bin/env bash
# Run the opt-in Python Until proof in the existing hardened browser image.
set -euo pipefail

task_root=$(cd -- "$(dirname -- "$0")/../.." && pwd)
task_output_arg=${1:?usage: run-python-until.sh /absolute/output [pytest arguments]}
shift
task_image=${YOSOI_YIELD_IMAGE:-yosoi-cas383:local}
task_mode=${YOSOI_YIELD_MODE:-headless}
case "$task_mode" in headless|headful) ;; *) printf '%s\n' 'mode must be headless or headful' >&2; exit 64;; esac

task_uv_command=${YOSOI_UV_EXECUTABLE:-$(type -P uv || true)}
if [[ -z $task_uv_command ]]; then
  printf '%s\n' 'uv is required on the host' >&2
  exit 64
fi
task_uv=$(realpath -e -- "$task_uv_command")
task_python_environment=${YOSOI_PYTHON_UV_ENV:-${UV_PROJECT_ENVIRONMENT:-$task_root/.venv}}
task_python_environment=$(realpath -e -- "$task_python_environment")
if [[ ! -x $task_python_environment/bin/python ]]; then
  printf 'existing synced UV environment has no interpreter: %s\n' "$task_python_environment" >&2
  exit 64
fi

if ! task_runtime_info=$( \
  UV_PROJECT_ENVIRONMENT="$task_python_environment" \
    "$task_uv" --quiet run --offline --project "$task_root" --no-sync python -c \
    'import sys, yosoi._native; print(f"{sys.version_info.major}.{sys.version_info.minor}"); print(sys.executable); print(sys.base_prefix); print(yosoi._native.__file__)' \
); then
  printf '%s\n' 'could not inspect the existing Python environment through UV' >&2
  exit 64
fi
task_python_version=${task_runtime_info%%$'\n'*}
task_runtime_tail=${task_runtime_info#*$'\n'}
task_python_executable=${task_runtime_tail%%$'\n'*}
task_runtime_tail=${task_runtime_tail#*$'\n'}
task_python_prefix=${task_runtime_tail%%$'\n'*}
task_native_extension=${task_runtime_tail#*$'\n'}
if [[ $task_python_version != 3.14 ]]; then
  printf 'the built native extension requires CPython 3.14; UV selected %s\n' "$task_python_version" >&2
  exit 64
fi
if [[ $task_python_executable != "$task_python_environment"/* || ! -x $task_python_executable ]]; then
  printf 'UV selected an interpreter outside the mounted environment: %s\n' "$task_python_executable" >&2
  exit 64
fi
task_python_prefix=$(realpath -e -- "$task_python_prefix")
task_python_mounts=(--mount "type=bind,src=$task_python_prefix,dst=$task_python_prefix,readonly")
# UV's environment may point through a stable interpreter alias while
# sys.base_prefix names its versioned target. Preserve that alias in Docker.
if [[ -L $task_python_environment/bin/python ]]; then
  task_interpreter_link=$(readlink -- "$task_python_environment/bin/python")
  if [[ $task_interpreter_link == /* ]]; then
    task_python_alias_prefix=$(dirname -- "$(dirname -- "$task_interpreter_link")")
    if [[ $task_python_alias_prefix != "$task_python_prefix" ]]; then
      task_python_mounts+=(--mount "type=bind,src=$task_python_prefix,dst=$task_python_alias_prefix,readonly")
    fi
  fi
fi
task_native_extension=$(realpath -e -- "$task_native_extension")
if [[ ! -d $task_python_prefix/lib || $task_native_extension != "$task_python_environment"/* || ${task_native_extension##*/} != _native*.so ]]; then
  printf '%s\n' 'the CPython base prefix or installed-wheel extension is missing; install the built wheel in the project UV environment first' >&2
  exit 64
fi

task_uv_cache=${UV_CACHE_DIR:-$("$task_uv" cache dir)}
task_uv_cache=$(realpath -e -- "$task_uv_cache")
if [[ ! -d $task_uv_cache ]]; then
  printf 'existing shared UV cache is unavailable: %s\n' "$task_uv_cache" >&2
  exit 64
fi
if [[ ! -f $task_root/pyproject.toml || ! -f $task_root/uv.lock ]]; then
  printf '%s\n' 'pyproject.toml and uv.lock are required by the Python runner' >&2
  exit 64
fi

task_output_arg=$(mkdir -p -- "$task_output_arg" && realpath -e -- "$task_output_arg")
chmod a+rwx -- "$task_output_arg"
task_image_id=$(docker image inspect "$task_image" --format '{{.Id}}')
task_browser=$(docker run --rm --entrypoint /bin/cat "$task_image_id" /usr/share/cas333/chromium-version.txt)
if [[ -n $(git -C "$task_root" status --porcelain) ]]; then
  printf '%s\n' 'installed-wheel browser proof requires a clean source checkout' >&2
  exit 64
fi
task_revision=$(git -C "$task_root" rev-parse HEAD)
task_container_uid=${YOSOI_CONTAINER_UID:-$(id -u)}
task_container_gid=${YOSOI_CONTAINER_GID:-$(id -g)}
if [[ $task_container_uid == 0 ]]; then
  printf '%s\n' 'the browser container must run as a non-root user' >&2
  exit 64
fi

printf 'source=%s image=%s browser=%s mode=%s python=%s output=%s\n' \
  "$task_revision" "$task_image_id" "$task_browser" "$task_mode" "$task_python_version" "$task_output_arg"
docker run --rm --init --network bridge --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --security-opt "seccomp=$task_root/docker/browser/seccomp-chrome.json" \
  --user "$task_container_uid:$task_container_gid" \
  --cpus 1 --memory 3g --memory-swap 3g --pids-limit 1024 \
  --shm-size 256m --tmpfs /tmp:rw,nosuid,nodev,size=768m,mode=1777 \
  --mount "type=bind,src=$task_uv,dst=$task_uv,readonly" \
  --mount "type=bind,src=$task_python_environment,dst=$task_python_environment,readonly" \
  "${task_python_mounts[@]}" \
  --mount "type=bind,src=$task_uv_cache,dst=$task_uv_cache" \
  --mount "type=bind,src=$task_root/python,dst=/workspace/python,readonly" \
  --mount "type=bind,src=$task_root/spikes/browser-automation/fixtures,dst=/workspace/spikes/browser-automation/fixtures,readonly" \
  --mount "type=bind,src=$task_root/pyproject.toml,dst=/workspace/pyproject.toml,readonly" \
  --mount "type=bind,src=$task_root/uv.lock,dst=/workspace/uv.lock,readonly" \
  --mount "type=bind,src=$task_root/spikes/browser-automation/python-until-profile.sh,dst=/usr/local/bin/cas333-profile-browser,readonly" \
  --mount "type=bind,src=$task_output_arg,dst=/evidence" \
  --env CHROME_NO_SANDBOX=0 --env YOSOI_BROWSER_TESTS=1 \
  --env YOSOI_EXPECT_INSTALLED=1 \
  --env "YOSOI_LIVE_SITE_TESTS=${YOSOI_LIVE_SITE_TESTS:-0}" \
  --env "YOSOI_LIVE_ITERATIONS=${YOSOI_LIVE_ITERATIONS:-3}" \
  --env "YOSOI_PYTHON_TEST_FILES=${YOSOI_PYTHON_TEST_FILES:-python/tests/test_until_browser.py}" \
  --env "YOSOI_YIELD_MODE=$task_mode" \
  --env YOSOI_BROWSER_OUTPUT_DIR=/evidence \
  --env "YOSOI_CONTAINER_UV=$task_uv" \
  --env "UV_PROJECT_ENVIRONMENT=$task_python_environment" \
  --env "YOSOI_PYTHON_BASE_PREFIX=$task_python_prefix" \
  --env "UV_CACHE_DIR=$task_uv_cache" \
  --env "YOSOI_SPIKE_SOURCE_REVISION=$task_revision" \
  --env "YOSOI_SPIKE_BROWSER_IDENTITY=$task_browser;image=$task_image_id" \
  "$task_image_id" "container-$task_mode" "$@"
