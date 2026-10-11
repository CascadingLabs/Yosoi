#!/usr/bin/env bash
# Run the isolated Python Until proof inside the existing hardened browser image.
set -euo pipefail

if [[ ${1:-} != --mode || ${3:-} != --environment-label ]]; then
  printf '%s\n' 'expected the Yosoi container profile argument prefix' >&2
  exit 64
fi
shift 4

task_root=/workspace
task_uv=${YOSOI_CONTAINER_UV:?UV executable path is required}
task_uv_environment=${UV_PROJECT_ENVIRONMENT:?existing UV environment path is required}
task_python_prefix=${YOSOI_PYTHON_BASE_PREFIX:?CPython base prefix is required}
task_uv_cache=${UV_CACHE_DIR:?existing shared UV cache path is required}

unset PYTHONPATH
export PYTHONDONTWRITEBYTECODE=1
export LD_LIBRARY_PATH="$task_python_prefix/lib"
export UV_PROJECT_ENVIRONMENT="$task_uv_environment"
export UV_CACHE_DIR="$task_uv_cache"
export UV_OFFLINE=1

cd "$task_root"
read -r -a task_tests <<< "${YOSOI_PYTHON_TEST_FILES:-python/tests/test_until_browser.py}"
set +e
"$task_uv" --quiet run --offline --no-sync --project "$task_root" \
  python -m pytest -p no:cacheprovider "${task_tests[@]}" -q "$@" \
  2>&1 | tee /evidence/python-until.log
task_status=${PIPESTATUS[0]}
set -e

if (( task_status != 0 )); then
  for task_counter in /sys/fs/cgroup/pids.events /sys/fs/cgroup/memory.events; do
    if [[ -r $task_counter ]]; then
      printf '\n%s\n' "$task_counter"
      cat -- "$task_counter"
    fi
  done
fi
exit "$task_status"
