#!/usr/bin/env bash
set -euo pipefail

if test "$#" -ne 2 || ! test -d "$1"; then
  printf 'usage: publish-benchmark-result.sh <completed-staging-directory> <destination>\n' >&2
  exit 2
fi
staging=$1
destination=$2
parent=$(dirname "$destination")
archive=""
cleanup() {
  status=$?
  trap - EXIT INT TERM
  if test -n "$archive" && test -d "$archive/result" && ! test -e "$destination"; then
    mv -- "$archive/result" "$destination"
    rmdir -- "$archive"
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if test -e "$destination"; then
  history="$parent/history/$(basename "$destination")"
  mkdir -p "$history"
  archive=$(mktemp -d "$history/$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")
  mv -- "$destination" "$archive/result"
fi
mv -- "$staging" "$destination"
trap - EXIT INT TERM
