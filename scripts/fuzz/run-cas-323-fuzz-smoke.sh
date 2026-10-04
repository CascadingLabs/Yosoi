#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root/fuzz"
if ! cargo fuzz --help >/dev/null 2>&1; then
  printf 'cargo-fuzz is required; install it with cargo install cargo-fuzz --version 0.13.1 --locked\n' >&2
  exit 1
fi
for target in wire-and-evidence http-input-boundaries bounded-lifecycle; do
  mkdir -p "corpus/$target"
  cp -f "seeds/$target/"* "corpus/$target/"
done

cargo +nightly fuzz run wire-and-evidence -- -runs=2000 -max_len=16384
cargo +nightly fuzz run http-input-boundaries -- -runs=2000 -max_len=4096
cargo +nightly fuzz run bounded-lifecycle -- -runs=2000 -max_len=2560
