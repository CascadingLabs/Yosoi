#!/usr/bin/env bash
set -euo pipefail

if test "$#" -ne 1; then
  printf 'usage: benchmark-result-directory.sh <measurement-class>\n' >&2
  exit 2
fi
case "$1" in
  criterion|callgrind|allocations|process|heap|browser) ;;
  *) printf 'invalid measurement class: %s\n' "$1" >&2; exit 2 ;;
esac

if command -v jj >/dev/null 2>&1 && jj root >/dev/null 2>&1; then
  change=$(jj log -r @ --no-graph -T 'change_id')
  printf 'benchmarks/results/by-change/jj/%s/%s\n' "$change" "$1"
elif command -v git >/dev/null 2>&1 && git rev-parse --show-toplevel >/dev/null 2>&1; then
  commit=$(git rev-parse HEAD)
  printf 'benchmarks/results/by-change/git/%s/%s\n' "$commit" "$1"
else
  printf 'benchmark results require a JJ change or Git commit identity\n' >&2
  exit 1
fi
