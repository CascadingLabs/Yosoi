# Map CLI verification

The initial observations below are historical. XML discovery, public-provider
concurrency, stats aliases, and broader live inventory comparisons supersede the
initial gaps; see [Map discovery verification](map-discovery-verification.md). (CAS-528)

## Implemented

The first-class `yosoi map` command binds the existing SDK after current-version
Policy profile resolution and explicit one-run overrides. Request and Map share
only stdout destination detection and HTTPS shorthand. The CLI owns no provider
transport or discovery implementation. A pure Map SDK preflight is shared by
`validate()` and dispatch so Explain uses the same admission/acquisition rules.

Terminal output shows seed, hosts, tree/status and source issues. File redirects
store a versioned JSON manifest. Bare pipes emit that manifest as one existing
YSOIDOC1 JSON Document, consumable by Locate JSONPath. Explicit JSON/raw and typed
output overrides are supported. Serialization stops at 16 MiB before any frame
is emitted; original response bytes are excluded. Cancellation awaits cleanup.
Profile files remain read-only. Completions and the hands-on script are updated.

## Focused local evidence

The isolated implementation passed all 86 CLI checks (28 unit, 58 process),
including 13 independent Map process cases, plus 68 facade/Map checks (25 library,
24 E2E,14 limits,5 audit). Production Clippy for the CLI and facade passed with
warnings denied. Builds/tests were serial with one worker and serial test threads.
No browser was launched and no full-repository or hosted-CI claim is made.

Process cases cover profiles, mode/limit overrides, invalid preflight, shorthand,
regular-file JSON, typed Map-to-Locate pipes, raw JSON, saved-frame replay,
normalization/subtree/robots dispatch, metadata absence/failure, limits/frontier,
Ctrl-C active response cleanup, and a closed output consumer. Existing malformed
and oversized Document frame rejection tests also passed. A bounded writer test
covers the exact serialization cap and first rejected byte.

Real Python PTY checks exercised terminal routing with loopback HTTP responses:
optional metadata404/410 printed no source issue and returned0; a robots503
(default Ignore) printed the issue once and returned3 with inspected page data.
The fixture and PTY waited on I/O/task completion, not sleeps. Independent review
caught and corrected benign404 warnings and duplicate support/source messages;
the final scoped review recommended Pass. Initial compile/lint and two schema
mismatches were corrected before the passing integrated checks.

## Live evidence

[Manifest](../evidence/map-cli/manifest.json) records exact isolated source and
executable hash. [QScrape JSON](../evidence/map-cli/qscrape.json) came from a regular
stdout file redirect:21 requests,19 URLs, selected work exhausted. It returned3
because the declared sitemap completed while conventional sitemap paths returned
HTML and failed XML parsing. Source errors remain explicit in otherwise useful
page results. [Map-to-Locate output](../evidence/map-cli/pipe.json) matched page URLs;
[process statuses](../evidence/map-cli/pipe-status.json) preserve Map3/Locate0.

[Anthropic passive JSON](../evidence/map-cli/anthropic-passive.json) records exactly
one crt.sh request and zero target-site requests. The source returned404, so the
CLI returned1 and retained its seed-only unverified inventory and failed source
status. This is real failure-isolation evidence, not a positive provider sample
or exhaustive subdomain result. There was no hidden retry or alternate source.

## Delivery

The reviewed feature `935b6ffc6faa36472873445f904caaf2c29b12c2` is integrated
into `/home/andrew/Desktop/cl/YosoiOxide` for Andrew's final live pass. Default
passed all86 CLI checks again. A fresh default-built executable repeated the
QScrape page smoke successfully:21 requests,19 URLs,exit3 for the recorded
optional sitemap parse failures. [Default status/hash](../evidence/map-cli/default-status.json)
and [default JSON](../evidence/map-cli/default-qscrape.json) distinguish this build
from the isolated executable above. Original feature bookmark `map-cli` remains preserved. This is
local convergence, not a remote-main push or a Done transition. Known Map limits
remain: one passive source, no browser discovery, and metadata can consume global
budgets before seed inspection on large sites such as Yahoo.
