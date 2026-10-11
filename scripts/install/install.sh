#!/bin/sh
# Install a verified prebuilt CLI. Usage: sh install.sh [--version VERSION] [--install-dir DIR]
set -eu

fail() { printf 'yosoi installer: %s\n' "$*" >&2; exit 1; }
version=${YOSOI_VERSION:-}
install_dir=${YOSOI_INSTALL_DIR:-"$HOME/.local/bin"}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --version) [ "$#" -ge 2 ] || fail '--version needs a value'; version=$2; shift 2 ;;
        --install-dir) [ "$#" -ge 2 ] || fail '--install-dir needs a value'; install_dir=$2; shift 2 ;;
        --help) printf 'Usage: sh install.sh [--version 0.MINOR.PATCH] [--install-dir DIR]\n'; exit 0 ;;
        *) fail "Unknown argument: $1" ;;
    esac
done
for tool in curl tar mktemp awk grep; do
    command -v "$tool" >/dev/null 2>&1 || fail "Required command missing: $tool"
done
case $(uname -s) in
    Linux)
        command -v getconf >/dev/null 2>&1 || fail 'Linux requires glibc 2.39 or newer'
        libc=$(getconf GNU_LIBC_VERSION 2>/dev/null) || fail 'Linux requires glibc; musl is unsupported'
        printf '%s\n' "$libc" | awk 'BEGIN { valid=0 } $1 == "glibc" { split($2, v, "."); valid=(v[1] > 2 || (v[1] == 2 && v[2] >= 39)) } END { exit !(valid && NR == 1) }' || fail 'Linux requires glibc 2.39 or newer (for example Ubuntu 24.04)'
        os=linux ;;
    Darwin)
        major=$(sw_vers -productVersion | cut -d . -f 1)
        [ "$major" -ge 11 ] || fail 'macOS 11.0 or newer is required'
        os=macos ;;
    *) fail 'Supported systems: Linux and macOS. Use install.ps1 for Windows.' ;;
esac
case $(uname -m) in
    x86_64|amd64) arch=x86_64 ;;
    aarch64|arm64) arch=aarch64 ;;
    *) fail 'Supported CPUs: x86-64 and ARM64' ;;
esac
case "$install_dir" in /*) ;; *) fail '--install-dir must be an absolute path' ;; esac
[ ! -L "$install_dir/yosoi" ] || fail "Refusing to replace a symlink at $install_dir/yosoi. If this is the old Python CLI, run: uv tool uninstall yosoi"
[ ! -d "$install_dir/yosoi" ] || fail 'Destination is a directory'
work=$(mktemp -d)
staged=
trap 'rm -rf "$work"; if [ -n "$staged" ]; then rm -f "$staged"; fi' EXIT HUP INT TERM
base=https://github.com/CascadingLabs/Yosoi/releases
download() { curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fLsS --retry 2 --connect-timeout 15 --max-time 300 "$1" -o "$2"; }
if [ -z "$version" ]; then
    download "$base/latest/download/release-plan.json" "$work/plan.json"
    version=$(sed -n 's/^[[:space:]]*"version": "\([^"]*\)",\{0,1\}[[:space:]]*$/\1/p' "$work/plan.json")
fi
case "$version" in *[!0-9.rc-]*) fail 'Invalid release version' ;; esac
printf '%s\n' "$version" | grep -Eq '^0\.[1-9][0-9]*\.(0|[1-9][0-9]*)(-rc\.[1-9][0-9]*)?$' || fail 'Invalid release version'
asset="yosoi-v$version-$os-$arch.tar.gz"
url="$base/download/v$version"
download "$url/SHA256SUMS" "$work/SHA256SUMS"
download "$url/$asset" "$work/$asset"
expected=$(awk -v asset="$asset" '$2 == asset { print $1 }' "$work/SHA256SUMS")
[ "${#expected}" -eq 64 ] || fail 'Missing or duplicate archive checksum'
case "$expected" in *[!0-9a-f]*) fail 'Invalid archive checksum' ;; esac
if command -v sha256sum >/dev/null 2>&1; then
    actual=$(sha256sum "$work/$asset" | awk '{print $1}')
elif command -v shasum >/dev/null 2>&1; then
    actual=$(shasum -a 256 "$work/$asset" | awk '{print $1}')
else
    fail 'Install sha256sum or shasum to verify downloads'
fi
[ "$actual" = "$expected" ] || fail 'Archive checksum mismatch'
[ "$(tar -tzf "$work/$asset")" = yosoi ] || fail 'Unexpected archive contents'
tar -xzf "$work/$asset" -C "$work"
[ -f "$work/yosoi" ] && [ ! -L "$work/yosoi" ] || fail 'Archive must contain a regular executable'
chmod 755 "$work/yosoi"
[ "$("$work/yosoi" --version)" = "yosoi $version" ] || fail 'Downloaded CLI version does not match the release'
mkdir -p "$install_dir"
staged=$(mktemp "$install_dir/.yosoi.XXXXXX")
cp "$work/yosoi" "$staged"
chmod 755 "$staged"
mv -f "$staged" "$install_dir/yosoi"
staged=
printf 'Installed Yosoi %s to %s/yosoi\n' "$version" "$install_dir"
case ":$PATH:" in
    *":$install_dir:"*) printf 'Run: yosoi --help\n' ;;
    *) printf 'Add %s to PATH, then run yosoi --help.\n' "$install_dir" ;;
esac
