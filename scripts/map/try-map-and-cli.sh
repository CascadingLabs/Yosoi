#!/usr/bin/env bash
# Build once, then exercise the CLI and the Map SDK from this checkout.
set -euo pipefail

if [[ ${1:-} == --help || ${1:-} == -h || $# -gt 2 ]]; then
  printf 'Usage: %s [URL] [pages|passive|combined]\n' "$0"
  printf 'Default: https://qscrape.dev/l1/news/ pages\n'
  printf 'Passive mode queries crt.sh only; it skips target-site CLI requests.\n'
  exit 0
fi
review_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd -- "$review_root"
review_seed=${1:-https://qscrape.dev/l1/news/}
review_mode=${2:-pages}
case "$review_mode" in
  pages|passive|combined) ;;
  *) printf 'Mode must be pages, passive, or combined.\n' >&2; exit 64 ;;
esac
export CARGO_TARGET_DIR=${CARGO_TARGET_DIR:-"$review_root/target"}

# One Cargo worker; browser support is compiled for the existing CLI,
# but all requests in this script use Direct HTTP.
cargo build --locked --offline -j 1 -p yosoi-cli -p yosoi \
  --bin yosoi --example map_review --features yosoi/browser
review_cli="$CARGO_TARGET_DIR/debug/yosoi"
review_map="$CARGO_TARGET_DIR/debug/examples/map_review"

if [[ $review_mode != passive ]]; then
  printf '\nCLI version and Policy:\n'
  "$review_cli" --version
  "$review_cli" policy path
  "$review_cli" policy validate
  printf '\nCLI Request outcome:\n'
  "$review_cli" request "$review_seed" --acquisition http --timeout-ms 15000 --json --stats
  printf '\nCLI Request -> Locate (typed Document pipe):\n'
  "$review_cli" request "$review_seed" --acquisition http --timeout-ms 15000 \
    | "$review_cli" locate --css 'a[href]' --json
fi
printf '\nMap CLI:\n'
# A partial Map remains useful; show its output and continue the SDK comparison.
if "$review_cli" map "$review_seed" --mode "$review_mode" \
    --depth 2 --max-requests 20 --max-hosts 2000 --stats; then
  :
else
  review_status=$?
  if [[ $review_status == 3 ]]; then
    printf 'Map CLI returned useful partial results (exit 3).\n' >&2
  else
    exit "$review_status"
  fi
fi
printf '\nMap SDK:\n'
"$review_map" "$review_seed" "$review_mode"
