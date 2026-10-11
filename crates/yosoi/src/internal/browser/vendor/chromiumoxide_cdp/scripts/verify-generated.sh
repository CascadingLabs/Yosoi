#!/usr/bin/env bash
set -euo pipefail

crate_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$crate_root"

sha256sum --check PDL.SHA256
sha256sum --check GENERATED.SHA256

grep -Fq 'pub const CURRENT_REVISION: Revision = Revision(1681091);' src/lib.rs
grep -Fq 'schema version `0.10.0-yosoi.m153.1`' VENDORING.md
grep -Fq '`yosoi-chromiumoxide-cdp` version' VENDORING.md
grep -Fq -- '- Chrome: `153.0.8010.36`' VENDORING.md
grep -Fq -- '- Chromium revision: `r1681091`' VENDORING.md
grep -Fq 'f343157cebb388bfa416baccb5d35507e6fe8cc7' VENDORING.md

printf '%s\n' 'Chrome 153 CDP inputs, generated output, and private module provenance verified'
