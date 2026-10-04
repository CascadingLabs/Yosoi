#!/usr/bin/env bash

set -euo pipefail

readonly TOOLCHAIN="1.99.0"
readonly NEXTEST_VERSION="0.9.106"
readonly DENY_VERSION="0.19.0"

if ! command -v rustup >/dev/null 2>&1; then
  echo "error: rustup is required; install it from https://rustup.rs/" >&2
  exit 1
fi

rustup toolchain install "${TOOLCHAIN}" \
  --profile minimal \
  --component clippy \
  --component rustfmt

actual_version="$(rustup run "${TOOLCHAIN}" rustc --version)"
expected_prefix="rustc ${TOOLCHAIN} "

if [[ "${actual_version}" != "${expected_prefix}"* ]]; then
  echo "error: expected ${expected_prefix}but found ${actual_version}" >&2
  exit 1
fi

rustup run "${TOOLCHAIN}" cargo metadata --no-deps --format-version 1 >/dev/null

nextest_version="$(rustup run "${TOOLCHAIN}" cargo nextest --version 2>/dev/null || true)"
if [[ "${nextest_version}" != "cargo-nextest ${NEXTEST_VERSION} "* ]]; then
  rustup run "${TOOLCHAIN}" cargo install cargo-nextest \
    --version "${NEXTEST_VERSION}" \
    --locked
  nextest_version="$(rustup run "${TOOLCHAIN}" cargo nextest --version)"
fi

deny_version="$(rustup run "${TOOLCHAIN}" cargo deny --version 2>/dev/null || true)"
if [[ "${deny_version}" != "cargo-deny ${DENY_VERSION}" ]]; then
  rustup run "${TOOLCHAIN}" cargo install cargo-deny \
    --version "${DENY_VERSION}" \
    --locked
  deny_version="$(rustup run "${TOOLCHAIN}" cargo deny --version)"
fi

printf 'Yosoi Oxide toolchain ready: %s\n' "${actual_version}"
printf 'Yosoi Oxide test runner ready: %s\n' "${nextest_version}"
printf 'Yosoi Oxide dependency policy ready: %s\n' "${deny_version}"
