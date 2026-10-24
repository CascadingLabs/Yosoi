# Runnable SDK review examples

## Surface readers

From a Yosoi source checkout with an installed matching wheel:

```sh
uv run --no-sync python python/examples/surface_read.py
uv run --no-sync python python/examples/surface_video.py recording.mp4 video-output
uv run --no-sync python python/examples/surface_video_replay.py video-output
```

`surface_read.py` acquires the live QScrape lamp page, searches captured HTML,
archives its Document, and reports whether restoration preserves the index
identity. Pass URL, literal query and archive directory as positional arguments
to use another document. This reads evidence; it does not control a browser.

`surface_video.py` requires a wheel built with `surface-video` and local FFmpeg
and FFprobe. It saves a frame and crop at 3.5 seconds, archives the source and
crop, and writes `evidence.json` with typed references and actual pixel/timestamp
metadata. Use `--position-us` for a different position. Local Archive currently
requires Unix. Live-stream subscription, OCR and audio decoding are unsupported.
`surface_video_replay.py` restores the saved timeline and crop in a new process;
it does not need either video tool or the original video path.

The corresponding Rust examples are `surface_read` and `surface_video` (the
latter requires `--features surface-video`).

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
schema, native transport schema and compiled plan, assembled candidates,
Pydantic-validated records, and field errors. `runtime-contracts` reviews
schema-authored Rust extraction, validation, and portable archival. `errors`
prints Rust error variants and payloads, plus a Map rejection message returned
by Rust. `local` starts a loopback HTTP server and exercises Requests and Map
plus explicit cancellation before I/O. These commands need no public website.
Fresh installed-wheel verification for the new Contract example is pending.

`browser_beta.py` is an application integration template rather than a
self-contained browser fixture. It expects the caller to provide typed site
actions and Until expectations, a Plan for its Contract, and browser settings.
The example uses no embedded selectors. It shows both managed invocation and
borrowed Session/Work ownership through the flat `import yosoi as ys` API. Its
order check explicitly stops the invocation on failure or cancellation so a
later order action cannot run after a failed assertion; this leaves the Rust
`Continue` defaults unchanged for other flows.

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
Rust runner command. These examples show selected SDK paths. Python Contracts
use Rust to locate and group evidence, then Pydantic to construct and validate
records. The separate `runtime-contracts` path demonstrates Rust-owned staged
validation and archives.

For source review before rebuilding the editable package in this checkout, use
`PYTHONPATH=python .venv/bin/python` in place of `uv run --no-sync python`.
Async examples need local socket access, including the event-loop wakeup socket.
