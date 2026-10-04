#!/usr/bin/env bash
# Produce a disposable, complete source context without VCS state, outputs, or secrets.
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
context=${1:-}
if [ -z "$context" ]; then
  context=$(mktemp -d "${TMPDIR:-/tmp}/cas333-container-context.XXXXXX")
fi

if [ ! -f "$root/Cargo.toml" ] || [ ! -f "$root/crates/voidcrawl/Cargo.toml" ] || [ ! -f "$root/vendor/chromiumoxide/Cargo.toml" ]; then
  printf 'YosoiOxide absorbed browser engine or vendored chromiumoxide source is unavailable\n' >&2
  exit 1
fi

# Copy the complete Yosoi workspace, including the absorbed browser engine and
# vendored chromiumoxide that Cargo resolves from the workspace root.
mkdir -p "$context/YosoiOxide" "$context/docker/browser"
copy_source() {
  local source=$1 destination=$2
  local -a excludes=(
    --exclude='.git/' --exclude='.jj/' --exclude='.pi/' --exclude='.agents/'
    --exclude='.local/' --exclude='.generated/' --exclude='__pycache__/'
    --exclude='target/' --exclude='target-*/' --exclude='results/' --exclude='.yosoi/' --exclude='.voidcrawl/'
    --exclude='node_modules/' --exclude='coverage/' --exclude='dist/' --exclude='build/'
    --exclude='.env' --exclude='.env.*' --exclude='.env/' --exclude='keys/' --exclude='secrets/'
    --exclude='.ssh/' --exclude='.aws/' --exclude='credentials/' --exclude='*.key' --exclude='*.pem'
    --exclude='*.p12' --exclude='*.pfx' --exclude='*.crt' --exclude='*.age' --exclude='*.sops'
  )
  rsync -a --delete "${excludes[@]}" "$source/" "$destination/"
}
copy_source "$root" "$context/YosoiOxide"

# Docker files are deliberately copied from the checked-out source after rsync
# so their inclusion does not depend on a future ignore rule.
cp "$root/docker/browser/Dockerfile" "$root/docker/browser/entrypoint.sh" \
  "$root/docker/browser/seccomp-chrome.json" "$root/docker/browser/seccomp-chrome.LICENSE" \
  "$context/docker/browser/"
cp "$root/docker/browser/.dockerignore" "$context/.dockerignore"
printf '%s\n' "$context"
