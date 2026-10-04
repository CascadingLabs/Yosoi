# Requests CLI

`yosoi request URL` runs the public Yosoi Requests SDK with the current CLI
version's active JSON Policy profile. With no active profile it uses this
binary's `Policy::default()`. `--profile NAME` selects a saved
profile for one invocation; it works before or after `request` and never edits
the Policy file. See [CLI Policy profiles](cli-policy-profiles.md) for the store.
The CLI prepends `https://` when the target has no URL scheme, so
`httpbin.org/html` works as written. It does not add `www` or change a supplied
host, subdomain, or path. Explicit `http://` and `https://` targets remain as
authored; the public SDK still validates the resulting full URL.

```sh
yosoi request https://example.org/
yosoi --profile next-run request https://example.org/ --explain
yosoi request https://example.org/ --profile next-run --json
yosoi request https://example.org/ --raw > response.txt
yosoi request httpbin.org/html -a headless --json
yosoi request httpbin.org/html -a http -s > response.html
```

Without an output flag, a terminal shows the human summary, `> file` writes
one complete produced Document's canonical bytes, and `|` emits a typed
Document frame. This routing uses the stdout descriptor type; a pipe to `cat`,
`jq`, or `tee` also receives the typed frame. Use explicit `--raw` for an
ordinary raw-byte pipe, `--pipe-document` to save a typed frame to a file, or
`--json` for a versioned summary without payload bytes.
Automatic redirect/pipe classification is currently supported on Unix;
other platforms require an explicit non-terminal output mode.

Raw output adds no newline. If a Policy requests multiple
acquisitions or Document views, specify `--attempt NUMBER` (one-based) and
`--document response|dom|ax|network` to choose the output. Raw output is
limited to 16 MiB. Its exit status reflects all requested outcomes; if the
selected Document is complete but another outcome failed, a brief diagnostic
goes to stderr. Redirect stdout to write a file; the CLI itself does not open
an output path.

The inferred pipe mode and explicit `--pipe-document` use the same selection
rules and emit one typed, binary-safe Document frame. See
[Locate CLI and Document pipes](cli-locate.md).

Per-run `-a` or `--acquisition http|headless|headful` may be repeated to replace the
profile's ordered acquisition list. `--timeout-ms` changes the per-attempt
deadline; `--content-coded-bytes`, `--representation-bytes`, and
`--unicode-bytes` set the corresponding source limits. These flags create one
validated Policy copy and do not change saved JSON. `--explain` shows that
complete Policy and identity after URL validation and before network I/O.

A received HTTP 404 is a response, not a transport failure. The CLI returns
nonzero when request setup fails, an acquisition fails or is not started, a
requested Document is incomplete or unavailable, or raw selection is invalid.
Ctrl-C requests cancellation from the SDK, waits for its terminal outcome, and
returns status 130 when that cancellation is observed.
Diagnostics go to stderr; raw, typed-pipe, and JSON stdout contain only their
selected output. General response headers remain follow-up work because the
current public Request outcome does not expose a complete header view.
`-s` or `--stats` (also `--stat`) adds wall time, termination, acquisition, HTTP status, and
retained Document byte counts on stderr after the request. It works with raw,
typed-pipe, JSON, and terminal output without changing stdout.
