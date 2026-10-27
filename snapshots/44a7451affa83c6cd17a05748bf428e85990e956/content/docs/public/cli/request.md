---
title: 'Request a document'
description: 'Acquire a URL and choose human, JSON, byte or typed Document output.'
order: 0
---

# Request a document

Use Request when the URL is known. The selected Policy controls acquisition and resource bounds.

## Fetch source bytes

```sh
# Save one complete selected Document as ordinary bytes.
yosoi request https://example.org/ --raw > page.html
```

The URL is a public demonstration page. Your application can provide its own known URL.

## Inspect attempts

```sh
# Read the outcome summary instead of dumping document bytes.
yosoi request https://example.org/ --json
```

Inspect attempt state, HTTP metadata and document outcomes. A returned summary can contain an unsuccessful acquisition or an unavailable representation.

## Send a typed Document downstream

```sh
set -o pipefail
# Keep the Document identity and profile in the Yosoi frame.
yosoi request https://example.org/ --pipe-document | yosoi locate --pipe-document --css 'h1' --json
```

Both sides explicitly select the typed Document format. Use raw bytes with a declared format when interoperating with ordinary files or other programs.

## Choose acquisition and bounds

```sh
yosoi request https://example.org/ --acquisition http --timeout-ms 5000 --json
```

The CLI timeout is in milliseconds. Repeating `--acquisition` replaces the Policy's ordered acquisition list; it does not define fallback-only behavior. Headless or headful browser acquisition needs a supported regular browser installation and its sandbox.

Use `--explain` to inspect the validated Policy before network I/O. Use `--attempt` and `--document` to select a specific available representation when emitting bytes or a typed frame.

See [Policy profiles](policy.md), [Locate](locate.md), or `yosoi request --help`.
