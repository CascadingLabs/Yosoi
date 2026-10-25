#!/bin/bash
set -euo pipefail
destination=${1:?provide an absolute engine directory}
case "$destination" in /*) ;; *) echo 'engine directory must be absolute' >&2; exit 64 ;; esac
case "$(uname -sm)" in 'Linux x86_64') ;; *) echo 'native acceptance installer requires Linux amd64' >&2; exit 64 ;; esac
mkdir -p "$destination/moli"
curl --fail --location --proto '=https' --tlsv1.2 \
    https://github.com/lexmount/moli/releases/download/v1.1.19/moli-x86_64-unknown-linux-gnu.tar.gz \
    --output "$destination/moli.tar.gz"
printf '%s  %s\n' 5c22362065e64e6de785274f6b3f28a735fca363abf9896c48733e5f58489def "$destination/moli.tar.gz" | sha256sum --check -
tar -xzf "$destination/moli.tar.gz" --strip-components=1 -C "$destination/moli"
curl --fail --location --proto '=https' --tlsv1.2 \
    https://archive.mozilla.org/pub/firefox/releases/158.0.1/linux-x86_64/en-US/firefox-158.0.1.tar.xz \
    --output "$destination/firefox.tar.xz"
printf '%s  %s\n' dce45470139242cf294eb6ada3d192a9bb334696842b02b71ade448a139eb41a "$destination/firefox.tar.xz" | sha256sum --check -
tar -xJf "$destination/firefox.tar.xz" -C "$destination"
"$destination/moli/moli" --version
"$destination/firefox/firefox" --version
