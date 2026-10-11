---
title: Python compatibility status
description: Declared interpreter targets and the exact local wheel and browser evidence currently available.
order: 6
---

# Python compatibility status

The package declares `>=3.12,<3.16` and requires Pydantic `>=2.14,<3`.
The current CI configuration selects CPython 3.12, 3.13, 3.14, and 3.15.0,
plus free-threaded CPython 3.14t and 3.15.0t. Those selections are targets,
not evidence that this candidate built or passed on each target.

## Current local candidate evidence

The evidence below was collected in the default Yosoi workspace on 2026-10-11.
The latest integration with main `46f9625a` has its own source-pinned wheel,
install and runtime reports. Earlier snapshots remain below as history.
The local development wheels use the `manylinux_2_39_x86_64` platform tag.
Each result applies only to its named source snapshot.

The verified integrated SDK source is
`5453ee65c417776bd7a72e3334c8017c199ff664`. Wheels built from its locked source
archive passed 307 consumer tests with eight skips on normal CPython 3.14.3 and
308 with seven skips on free-threaded CPython 3.14.7. Three installed-wheel
browser runs passed 13 tests each: normal headless, free-threaded headless and
mixed managed-headless/borrowed-headful invocation. All used regular Chrome
Stable 155.0.8059.39. Source, wheel, installed extension and JUnit hashes are
retained in the reports. Nine semantic suites passed 1,030 comparisons on a
fresh compiler inventory for that source.

These are local Linux x86-64 development-artifact results. Release-profile
artifacts, full hosted interpreter/platform coverage and Chrome/CDP certification
remain separate gates in the [release checklist](../browser-automation-review/release.md).

### Earlier candidate evidence

Before the earlier candidates below, the later live-test source
`05995a173b988c152dc10758ab85c6c6de4ecdf1` added bounded navigation diagnostics
and opt-in live stress coverage. Its rebuilt free-threaded CPython 3.14.7 wheel
passed 308 consumer tests with 18 skips and nine live scenarios on regular
Chrome Stable 155.0.8059.39, including six confirmed Qscrape orders. Two rendering
probes remained expected failures; an earlier unknown navigation remains
recorded. These results are separate from the integrated-source loopback suites
and do not establish full framework coverage or certification.

| Source snapshot                                                                                                                 | Interpreter and wheel                   | Result                                                                                                                                                             |
| ------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| SDK source revision `1f172423e03ce367a65ab99d8e6c7a06e22bf6bb`                                                                  | Free-threaded CPython 3.14.7t, `cp314t` | Refreshed installed-wheel headless browser run: 13 tests passed. The wheel SHA-256 is `ae5d4da7f0bbc6ab9104662e46ba922509d649c8b4fe461fd949d7d92bf75c61`.          |
| SDK source revision `1f172423e03ce367a65ab99d8e6c7a06e22bf6bb`                                                                  | Rust/Python semantic comparison report  | Nine semantic suites passed 1,030 comparisons (244 + 262 + 60 + 22 + 24 + 194 + 122 + 6 + 96). This verifies those suites, not complete API parity.                |
| Request-integrated revision `6c2638294048897a32d5f5c68fb72bba99b38d23` plus local Clippy and `SessionRequest` metadata fixes    | Free-threaded CPython 3.14.7t, `cp314t` | Installed-wheel consumer suite: 308 passed and 7 skipped. Browser-opt-in checks were skipped in this run.                                                          |
| Source archive made from revision `6c2638294048897a32d5f5c68fb72bba99b38d23` plus its local Clippy-only request future/drop fix | CPython 3.14.3, `cp314`                 | Browser-enabled wheel built from the archive and installed into a consumer environment: 307 passed and 8 skipped. Browser-opt-in tests were skipped in this suite. |
| Earlier candidate revision `05078b5e943f0d8f4be70261c9d201f7c7769216`, before the request integration                           | CPython 3.14.3, `cp314`                 | Installed-wheel suite: 305 passed and 7 skipped.                                                                                                                   |
| Earlier candidate revision `05078b5e943f0d8f4be70261c9d201f7c7769216`, before the request integration                           | Free-threaded CPython 3.14.7t, `cp314t` | 10 tests passed in a mixed run: managed invocations were headless and borrowed invocations were headful. This is browser evidence, not a full Python suite result. |

The refreshed revision `1f172423` headless run used Google Chrome Stable
155.0.8059.39, executable SHA-256
`9bfb381296dffe75f3419d07b6cc64525105ed117d1453a4ef3b291cb97d2b58`, in
browser image `sha256:a47b9407209e2f644f64bd49bab29cc5a35566c25ab221649d97fb5bb61b99f3`.
Its evidence report records the wheel member and installed native extension
hashes as well as the JUnit hash. The earlier headful run used the same Chrome
version and image. These are local loopback-fixture regression runs; they do
not certify the full CDP baseline.

The refreshed 1f172 wheel and reports were produced in the default workspace;
the integrated-source runs above supersede that pre-integration checkpoint. The
scoped SDK gate passed with no missing mappings and all nine required semantic
suites passing. The broader compiler inventory is a separate audit; this does
not establish individual behavioral evidence for every mapped declaration.
Hosted CI and publication are not represented by these local reports.

## Historical interpreter matrix

The following 282/283-test results are retained as historical local evidence.
They predate the current request-integrated source and do not verify it.

| Earlier source snapshot and date                       | Interpreter                                                       | Earlier installed-wheel result                          |
| ------------------------------------------------------ | ----------------------------------------------------------------- | ------------------------------------------------------- |
| `c26eace7b2dc746fcde1072748ff6cc6c7fe2114`, 2026-10-05 | CPython 3.12.14 (`cp312`), 3.13.1 (`cp313`), and 3.14.8 (`cp314`) | 282 passed, 1 free-threading-only skip per interpreter. |
| `c26eace7b2dc746fcde1072748ff6cc6c7fe2114`, 2026-10-05 | Free-threaded CPython 3.14.8t (`cp314t`)                          | 283 passed.                                             |
| `4c45cc76412351d1c438d309b683bbc0a453a86c`, 2026-10-09 | CPython 3.15.0 (`cp315`)                                          | 282 passed, 1 free-threading-only skip.                 |
| `4c45cc76412351d1c438d309b683bbc0a453a86c`, 2026-10-09 | Free-threaded CPython 3.15.0t (`cp315t`)                          | 283 passed.                                             |

The older repository report at `python/COMPATIBILITY.md`
contains details about those earlier runs. Its matrix is not a current
compatibility claim for the request-integrated source.

## Remaining evidence gaps

The logged candidate results cover Linux x86-64 only. They do not establish
the current source on every configured CPython version, operating system,
architecture, or libc baseline. Hosted CI completion, published wheels, and
registry-installed results are not claimed. Browser evidence is local and
does not replace the required monthly Chrome/CDP certification.

The [parity report](parity.md) tracks symbol-level Python/Rust coverage. The
repository's `python/examples/README.md` describes the available
local review commands.
