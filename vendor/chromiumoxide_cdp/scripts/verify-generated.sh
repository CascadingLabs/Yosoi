#!/usr/bin/env bash
set -euo pipefail

crate_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$crate_root"

sha256sum --check PDL.SHA256
sha256sum --check GENERATED.SHA256

grep -Fq 'pub const CURRENT_REVISION: Revision = Revision(1681091);' src/lib.rs
grep -Fq 'chrome-version = "153.0.8010.36"' Cargo.toml
grep -Fq 'chromium-revision = 1681091' Cargo.toml
grep -Fq 'v8-revision = "f343157cebb388bfa416baccb5d35507e6fe8cc7"' Cargo.toml

printf '%s\n' 'Chrome 153 CDP inputs, generated output, and revision metadata verified'
