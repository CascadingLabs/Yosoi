#!/usr/bin/env bash
# Adapt the existing hardened Yosoi entrypoint to the current SDK test binary.
set -euo pipefail
if [[ ${1:-} != --mode || ${3:-} != --environment-label ]]; then
  printf '%s\n' 'expected the Yosoi container profile argument prefix' >&2
  exit 64
fi
shift 4
if /spike/sdk-tests "$@"; then
  exit 0
else
  task_status=$?
  for task_counter in /sys/fs/cgroup/pids.events /sys/fs/cgroup/memory.events; do
    if [[ -r $task_counter ]]; then
      printf '\n%s\n' "$task_counter"
      cat -- "$task_counter"
    fi
  done
  exit "$task_status"
fi
