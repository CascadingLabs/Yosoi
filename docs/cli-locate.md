# Locate CLI and Document pipes

`yosoi locate` runs the public Yosoi locator facade over one Document. Raw file
or stdin bytes require an explicit source format:

```sh
yosoi locate --file page.html --format html --css 'h1'
cat data.json | yosoi locate --format json --json-path '$.name' --json
```

Choose exactly one query: `--css`, `--text`, `--json-path`, or
`--json-pointer`. The CLI builds one public Plan and projects its named
`match` output. It does not offer a separate parse command.

For a request pipeline, use the typed Document mode on both sides:

```sh
set -o pipefail
yosoi request https://example.org/ \
  | yosoi locate --css 'h1' --json
```

With `pipefail`, the shell also reports a Request failure when Locate succeeds
on a selected complete Document from a run whose other outcomes failed.

Request emits exactly one complete produced Document. With multiple
acquisitions or requested views, pass `--attempt NUMBER` and a `--document`
choice (`response`, `dom`, `ax`, or `network`) to Request. The typed stream carries a versioned,
length-bounded JSON header with the public Document ID and complete profile,
followed by exact binary bytes. Locate reconstructs the Document through the
public facade, preserving source, rendered DOM, accessibility representation,
and any document epoch. It rejects malformed, truncated, oversized, and
trailing input. Locate recognizes a typed frame on stdin without an input-mode
flag; raw stdin needs `--format`. Explicit `--pipe-document` and `--stdin`
remain available when the shell descriptor does not express the intended mode.
The typed frame is for CLI piping, not human-readable text.

Both commands use the current CLI version's active JSON Policy by default.
Use `--profile NAME` on each command to select another saved
profile for that invocation. Selection in Request does not silently transfer
to Locate across a process pipe.

The CLI caps raw inputs and typed payloads at 64 MiB, pipe headers at 8 KiB,
and rendered outcomes at 16 MiB. The default output gives a short human
summary; `--json` emits a versioned envelope with the Document profile and
the SDK's typed outcome. Exit codes are 0 for matched,
1 for complete no-match, 2 for indeterminate evidence, and 3 for a typed
Locate failure. Invalid CLI input or I/O also returns nonzero with a stderr
diagnostic.
