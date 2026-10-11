---
title: 'What earns a 0.2.0 release'
description: 'The current 0.2.0 beta scope, artifact targets and remaining release gates.'
order: 9
---

# What earns a 0.2.0 release

## October 11 preparation checkpoint

The default workspace contains the integrated Rust browser SDK, Python browser
SDK, private browser runtime, release tooling and docs publication pipeline.
CAS-574 is complete. PR #155 merged at
`46f8e561ee2d48a95485d84a2be32b6f7cee2bfb` on October 11. All 19 hosted
checks passed on its reviewed head `75ba3744`, including docs, installed Python
and semantic parity, Rust strict lint/build, tests and coverage. Main's exact
merge-commit checks are tracked separately; later packaging edits also require
their own final-source checks.

Local release metadata is synchronized at `0.2.0`, with citation date
`2026-10-11`. This is preparation metadata, not a published version. GitHub's
published comparison baseline is [v0.1.2](https://github.com/CascadingLabs/Yosoi/releases/tag/v0.1.2),
published October 11 at 05:57:20 UTC. Earlier notes saying integration, Python
completion or the version bump were still pending are superseded.

## Beta scope

Andrew accepted the current browser SDK limitations for beta. Further edge
cases and hardening follow real usage; deferred refinements do not become new
release blockers. This matrix describes the supported surface and the remaining
release assignment to review.

| Surface                | 0.2.0 preparation scope                                                                                                                                                                     |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Rust browser SDK       | Sessions, exclusive Work leases, browser Requests, typed actions, Flows, immediate assertions, scoped Until, millisecond timeouts and structured outcomes.                                  |
| Python browser SDK     | Async managed and borrowed invocation over the same engine, Session/Work context managers, Requests, typed Contract predicates, timeouts and cancellation.                                  |
| JavaScript             | Explicit permission, bounded construction-time file snapshots and local module graphs; selected exports are read as JSON-compatible values.                                                 |
| Rust Archive and Views | Existing bounded records and inspection remain available; final notes must state their release assignment explicitly. Stronger integrity, durability and replay guarantees remain deferred. |
| Python limits          | Initial Session tab and one borrowed Work lease. Explicit tab creation, Watcher streams, remote attachment and the Rust Archive/View facade are outside this Python beta surface.           |
| Browser runtime        | Regular Chrome/Chromium installed separately, with sandboxing enabled. Browser regression results and full Chrome/CDP certification remain separate evidence.                               |

Failure and local child cancellation default to Continue, with nearest-scope
Stop overrides. Outcomes retain failed and uncertain receipts; returning an
outcome does not mean every step succeeded. Python callers can use
`require_completed()` for a strict success path. Borrowed invocations do not
close the caller's Session or elevate its permissions. Unresolved cleanup can
fence a Work lease and return an error.

Firefox/BiDi, distributed placement, durable browser resumption, isolated
JavaScript worlds and package/network module imports are outside this release
scope. See [Python browser workflows](../python/browser-workflows.md) for current
examples and limits.

## Artifact targets

The existing Release CD matrix targets Linux x86-64 and ARM64 at manylinux 2.28,
Windows x86-64, and macOS Intel and Apple Silicon with an 11.0 minimum. It builds
five native CLI archives, one shared Python source distribution and 15 wheels.
Thirty installed-wheel checks cover CPython 3.12–3.15 plus free-threaded 3.14
and 3.15 across those five platforms. These are configured targets; completion
must be verified for the chosen release source.

Rust publication uses the existing package dependency order. The private browser
components are included in SDK sources and require no separate fork crate
publication. Independently versioned `yosoi-contracts-derive` moves to 0.1.2. Its source
changed during the CI repair, so reusing the already published 0.1.1 archive
would fail the immutable-source comparison. Release CD publishes the new helper
before the SDK through its existing dependency order; no registry upload has
occurred during preparation.

## Evidence already recorded

The integrated SDK source has local Linux x86-64 development-artifact proof:

- Normal CPython 3.14.3 installed consumer suite: 307 passed, eight skipped.
- Free-threaded CPython 3.14.7 installed consumer suite: 308 passed, seven skipped.
- Three installed-wheel browser runs: 13 tests each, covering normal headless,
  free-threaded headless and mixed managed-headless/borrowed-headful invocation.
- Regular Chrome Stable 155.0.8059.39 with source, wheel, native extension and
  JUnit hashes recorded in the reports.
- Nine Rust/Python semantic suites: 1,030 comparisons with no structural drift
  or missing supported SDK mappings. Individual behavioral coverage of the
  broader compiler inventory remains a separate audit.

The later rebuilt free-threaded wheel passed 308 consumer tests with 18 skips
and nine live scenarios, including six confirmed Qscrape orders. Two framework
rendering probes remained expected failures. An earlier unknown navigation
remains recorded; later successful runs do not relabel it. Live regression
evidence applies to `05995a17`, separately from the integrated-source suites above.

See [Python compatibility status](../python/compatibility.md) for the evidence
boundaries. These results do not establish release-profile artifacts, the full
platform matrix, registry installation or complete Chrome/CDP certification.
October 5 spike results remain historical evidence, not certification of the
current integrated source.

## Remaining release gates

The initial October 11 audit found 456 denied core Clippy diagnostics. The
repair now passes the complete local workspace/all-target/all-feature strict
lint gate and 78 focused model, assertion, Archive and View regressions. The
no-browser configuration compiles separately. No test declarations were
removed; the JSON Pointer regression is new.

[PR #155](https://github.com/CascadingLabs/Yosoi/pull/155) is merged. Its final
head passed all 19 hosted checks. Both Codex findings are resolved: native input
uses a retained unique element, and omitted Python Session settings inherit the
bound policy's browser mode. A focused sandboxed Chrome 155 regression verified
retained-target dispatch, ambiguous-target rejection and detached-target failure.
Earlier failing repair heads remain historical evidence.

- [x] Integrate the accepted browser and Python SDKs with the private runtime in default.
- [x] Record installed Python consumer/browser proof on the integrated SDK source.
- [x] Synchronize local `0.2.0` metadata and citation date through existing tooling.
- [x] State the beta shipping matrix: existing bounded Rust Archive records and Views
      are included; stronger durability/replay guarantees and Python facades remain deferred.
- [ ] Pass strict source CI for the exact chosen source: Rust format/lint/build,
      tests and doctests; Python installed-wheel and semantic gates; public docs.
      PR checks passed; merge-commit and packaging-source checks remain distinct.
- [ ] Complete applicable current Stable Chrome/CDP certification and controlled
      negative cases on the final source. Keep live-site results distinct.
- [ ] Build release-profile native and Python artifacts and pass the existing
      platform/interpreter installation matrix, including locked sdist rebuilds.
- [ ] Verify crate metadata, `yosoi-contracts-derive` prerequisite and artifact contents.
- [x] Prepare final beta `0.2.0` notes with the current `2026-10-11` metadata date.
      Synchronize the date through `bump-version` if the publication decision changes it.
- [x] Import authentic GitHub notes against `v0.1.2` from the reviewed repair ref
      and finalize [canonical 0.2.0 notes](../releases/0-2-0.md), preserving provenance.
- [ ] Pass `xtask release check` and present the publication decision with exact
      source identity, artifact hashes, hosted outcomes and remaining gaps.

Use the existing version, notes, CI and Release CD tooling. Run one expensive
local validation at a time with one worker. Keep required gates intact and
report skipped checks explicitly.

Preparation does not authorize tagging or publication. Candidates also publish
Python packages, images and docs when publication is enabled; selecting a
candidate does not make publication a local-only action.
