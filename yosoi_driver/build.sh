#!/usr/bin/env bash
# Build and install yosoi_driver into the current Python environment.
set -euo pipefail
cd "$(dirname "$0")"
maturin develop --release --manifest-path crates/pyo3_bindings/Cargo.toml
