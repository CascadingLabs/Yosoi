#!/usr/bin/env bash
# Inspect or remove only CAS-333 containers; never use Docker prune commands.
set -euo pipefail

label='com.cascadinglabs.yosoi.cas333=true'
usage() {
  printf 'usage: %s --check|--remove-stale\n' "$0" >&2
}

if [ "$#" -ne 1 ]; then
  usage
  exit 64
fi
case "$1" in
  --check|--remove-stale) mode=$1 ;;
  --help|-h) usage; exit 0 ;;
  *) usage; exit 64 ;;
esac

if ! command -v docker >/dev/null 2>&1; then
  printf 'docker is required\n' >&2
  exit 69
fi

containers=()
docker_output=$(docker ps --all --quiet --filter "label=$label")
if [ -n "$docker_output" ]; then
  mapfile -t containers <<<"$docker_output"
fi
for container in "${containers[@]}"; do
  # Docker emits hexadecimal IDs here. Refuse surprising output rather than passing it on.
  if [[ ! "$container" =~ ^[[:xdigit:]]{12,64}$ ]]; then
    printf 'unexpected Docker container ID returned by label query\n' >&2
    exit 1
  fi
done

case "$mode" in
  --check)
    if [ "${#containers[@]}" -eq 0 ]; then
      printf 'no CAS-333 labelled containers found\n'
      exit 0
    fi
    printf 'CAS-333 labelled containers remain:\n' >&2
    printf '%s\n' "${containers[@]}" >&2
    exit 1
    ;;
  --remove-stale)
    if [ "${#containers[@]}" -eq 0 ]; then
      printf 'no CAS-333 labelled containers found\n'
      exit 0
    fi
    for container in "${containers[@]}"; do
      # Each ID came from the exact label filter above; no broad remove or prune is used.
      docker rm --force -- "$container"
    done
    ;;
esac
