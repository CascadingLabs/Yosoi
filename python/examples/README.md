# Runnable SDK review examples

The earlier compatibility report exercised the seven commands that existed in
that SDK snapshot on normal 3.12, 3.13, 3.14, and exact 3.14.3t. It predates
the Contract example and does not verify the current Contract wheel. See
[the historical report](../COMPATIBILITY.md) and the public
[current compatibility status](../../docs/public/python/compatibility.md).

Run these from the repository root after creating an editable development
installation. The following selects normal CPython 3.12; use `3.13`,
`3.14`, or the exact free-threaded `3.14.8t` selector for the other
targets:

~~~sh
CARGO_BUILD_JOBS=1 uv sync --locked --python 3.12
uv run --no-sync python python/examples/review.py policy
uv run --no-sync python python/examples/review.py locate
uv run --no-sync python python/examples/review.py contracts
uv run --no-sync python python/examples/review.py runtime-contracts
uv run --no-sync python python/examples/review.py errors
uv run --no-sync python python/examples/review.py local
~~~

`policy` shows Rust defaults, policy identity, save/reload, and how an
existing binding keeps its validated policy snapshot. `locate` shows
Pydantic-authored plans, Rust compilation and execution, extraction evidence,
repeated-region lineage, and parse reuse. `contracts` prints the Pydantic model
schema, Rust Contract schema and compiled plan, extracted candidates, validated
records, and field issues. `runtime-contracts` reviews schema-authored extraction and
portable archival. `errors` prints Rust error variants and payloads, plus a Map
rejection message returned by Rust. `local` starts a loopback HTTP server and exercises
Requests and Map plus explicit cancellation before I/O. These commands need no public website. Fresh installed-wheel verification for the new Contract
example is pending.

For requests to public sites or search providers:

~~~sh
uv run --no-sync python python/examples/review.py request https://example.org/
uv run --no-sync python python/examples/review.py map https://example.org/
uv run --no-sync python python/examples/review.py search "Yosoi Rust SDK" --provider bing
uv run --no-sync python python/examples/review.py cancel https://example.org/
~~~

Network examples use bounded policies and an outer 45-second timeout. They
print typed SDK outcomes, including failure, unavailable, and cancellation
states. Search routes are previews; these examples do not certify providers.
Browser-backed routes require a Python extension built with the Rust
`browser` feature and a compatible regular Chrome or Chromium installation.
A wheel's native capabilities are fixed when it is built.

The public Rust SDK has review counterparts for the same commands:

~~~sh
CARGO_BUILD_JOBS=1 cargo run --locked --package yosoi --example review -- policy
CARGO_BUILD_JOBS=1 cargo run --locked --package yosoi --example review -- locate
CARGO_BUILD_JOBS=1 cargo run --locked --package yosoi --example review -- request https://example.org/
CARGO_BUILD_JOBS=1 cargo run --locked --package yosoi --example review -- map https://example.org/
CARGO_BUILD_JOBS=1 cargo run --locked --package yosoi --example review -- search "Yosoi Rust SDK"
CARGO_BUILD_JOBS=1 cargo run --locked --package yosoi --example review -- cancel https://example.org/
~~~

Pass `--features browser` before `--` to the Rust command when reviewing
browser-backed Search routes. The Python `local` example has no matching
Rust runner command. These examples show selected SDK paths; Python Contracts use the shared Rust
extraction and validation implementation.

For source review before rebuilding the editable package in this checkout, use
`PYTHONPATH=python .venv/bin/python` in place of `uv run --no-sync python`.
Async examples need local socket access, including the event-loop wakeup socket.
