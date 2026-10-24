# Homepage Contract example review

Source revision before this receipt: a116cd8d1d237def11f52acf311ea1da34d1c3e4.
Page: getting-started/what-is-yosoi.md. Public Rust facade and Python Contract implementation reviewed against the current working source.
Feature profile: Rust default features (none); Python existing project environment and installed native extension, without reinstalling or rebuilding it.

Rust snippet SHA-256: e429779584b233d8d35321fcc2f46ed60327603dbc6894e724cde85705d3378f.
Python snippet SHA-256: 33ea98371a65042f614797bd6a2e46379cb91e06b4950345d2563110f210732c.

- Rust: extracted the exact Markdown snippet into a temporary package example; cargo run --locked -p yosoi --example homepage_contract_check with CARGO_BUILD_JOBS=1 and RAYON_NUM_THREADS=1. Passed all visible assertions and printed Desk lamp costs $29.00. Removed the temporary source. Existing session dead-code warnings remain.
- Python: extracted the exact Markdown snippet and ran uv run --no-sync python from the project. Passed all visible assertions and printed Desk lamp costs $29.00. Removed the temporary source.
- Public documentation validation passed for paths, links, navigation and native Markdown rendering.
- No browser, network, server startup, hosted CI, release publication or deployment is claimed.
