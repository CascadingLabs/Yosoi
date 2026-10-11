# Yosoi 0.2.0 Python SDK release handoff (draft)

**Status:** internal preparation only. This is not canonical release notes, a
release decision, or approval to tag or publish.

The published comparison baseline, reverified on 2026-10-11, is `v0.1.2`
(publication time 05:57:20 UTC), targeting main `46f9625a`. The workspace
currently carries Cargo version `0.2.0`; `CITATION.cff` carries release date
`2026-10-11`, applied with the repository's existing `cargo xtask bump-version`
workflow. Those local metadata changes do not establish that `0.2.0` has been
released. No `v0.2.0` or release-candidate tag, crates.io upload, PyPI upload,
or GitHub release is authorized here.

The integration combines SDK revision `1f172423e03ce367a65ab99d8e6c7a06e22bf6bb`
with the `0.1.2` mainline at `46f9625`; separately published private browser
fork packages are not part of this integration. A fresh installed-wheel and
browser run from the assembled integration source passed; the results and exact
source identity are recorded below. Release-profile and hosted proof remain pending.

## What 0.2.0 adds

The Python package extends the existing SDK with async browser ownership and
reuse of the shared Rust engine. Applications can manage a `Session`, borrow a
`Work` lease, invoke typed Flows, and send a `PageRequest` through either
owner. Managed calls release resources they acquired; borrowed calls leave
Session and Work cleanup with the caller. Explicit Policies are checked
against the owning Session's browser mode and capabilities.

Flows retain Rust's `Continue` default for recoverable failures. A failure can
therefore be followed by another step unless the recipe selects an explicit
stop, such as `on_failure=ys.policy.Stop(scope="invocation")`. Outcomes keep
the failure receipt and may end as `completed_with_issues`; use
`require_completed()` when the caller needs a strict success path. Unknown
effects, root cancellation, and unsafe control states remain stop boundaries.

Timeout inputs are integer milliseconds. Typed Contract assertions capture
one canonical observation and pass the same located values to local
synchronous Python predicates. A false predicate and a raised predicate
exception have separate report states. Serialized recipes retain the Rust
assertion descriptor, not Python executable code; invocation requires the
matching in-memory bindings.

JavaScript files and local module graphs are bounded construction-time Rust
snapshots. Module imports stay within the supported local relative graph, and
selected exports are read as JSON-compatible values rather than invoked.
Managed invocation can explicitly grant JavaScript permission. A borrowed Work
cannot elevate its Session's permissions. Caller cancellation and Python task
cancellation reach the Rust operation; cancellation does not roll back a
dispatched effect. A synchronous assertion predicate may finish later on its
blocking worker, so predicates must stay short and pure.

## Deliberate limits for this Python surface

The Python browser bridge exposes the Session's initial tab and one borrowed
Work lease. Explicit tab creation, Watcher streams, remote attachment, and the
Rust Archive/View APIs are outside this scope. The bridge does not add another
browser executor. Firefox/BiDi, distributed placement, durable browser
resumption, isolated JavaScript worlds, and package or network module imports
are not 0.2.0 capabilities. The wheel does not bundle Chrome or Chromium.

The declared Python range is `>=3.12,<3.16`; the configured ABI matrix also
includes free-threaded 3.14 and 3.15. That declaration is not a promise that
every platform artifact or browser configuration has passed. Current local
browser evidence uses regular Chrome 155 on Linux and does not certify the
complete platform or controller matrix.

## Verification and release work

The verified SDK source is `5453ee65c417776bd7a72e3334c8017c199ff664`.
It includes main `46f9625a` and its private browser runtime. CAS-574 is Done;
both `python-browser-sdk-020` and `browser-actions-spike` identify this source.
The temporary integration workspace has been removed.

Pinned Maturin 1.15.0 exported a source archive containing the private controller,
generated CDP sources, and Python package. The existing sdist helper verified
locked package identities; both normal and free-threaded wheels built from that
archive. Installed consumer suites passed 307 tests with eight skips on CPython
3.14.3 and 308 with seven skips on free-threaded CPython 3.14.7.

All three installed-wheel browser runs passed 13 tests on regular Chrome Stable
155.0.8059.39: normal headless, free-threaded headless, and a mixed run with
managed headless and borrowed headful invocations. The reports record source,
wheel and installed native hashes, JUnit hashes, and browser identity. They are
loopback regression evidence, not full Chrome/CDP certification.

A fresh 389-page compiler inventory and all nine Rust/Python semantic suites
passed for this exact source: 1,030 comparisons, zero structural drift and no
missing supported SDK mappings. This does not claim individual behavioral
verification of every declaration in the broader compiler inventory.
Independent review found no supported-surface integration omissions. Strict
native bridge Clippy, public-doc formatting/links/render checks, and official
0.2.0 version/date consistency passed. No-browser compilation passed with three
core warnings.

Evidence is retained under `.local/cas574/`: `completion-audit.json`,
`core-parity-integrated/`, `integrated-wheels/`, `integrated-sdist/`,
`integrated-normal-headless/`, `integrated-free-headless/`, and
`integrated-free-headful/`. These are local Linux x86-64 development artifacts.
Hosted CI, release-profile artifacts, the full supported interpreter/platform
matrix, registry installations, and publication remain release gates.

The remaining release gates are:

- Build and install release-profile artifacts from the approved release source. Confirm
  the source archive build remains locked and the wheel contains the Python
  package and compiled native extension. Confirm the source archive contains
  the private Rust sources, vendored browser dependencies, and runtime assets
  needed to rebuild it.
- Run the scoped SDK gate on the chosen release source with its fresh
  compiler inventory and installed extension. Preserve the broader inventory
  audit and individual-item evidence counts separately from that gate.
- Complete the required hosted interpreter and platform matrix. Workflow
  configuration and the local CPython 3.14 wheels do not establish that matrix.
- Run the release preflight for the required crate metadata and registry
  prerequisites. Verify `yosoi-contracts-derive` 0.1.1 by version, checksum, and
  packaged contents; confirm its registry prerequisite before any authorized
  release run. The private browser fork packages are not registry prerequisites
  for this integration.
- Decide whether to prepare a numbered candidate or final beta. A candidate
  uses Cargo/tag version `0.2.0-rc.N` / `v0.2.0-rc.N` and Python version
  `0.2.0rcN`; the final beta uses `0.2.0` / `v0.2.0`. Select the candidate
  number and date only after scope is frozen, then synchronize metadata through
  `cargo xtask bump-version`.
- After the candidate revision is available on GitHub, obtain authentic generated notes for
  the selected comparison range. Prepare the canonical file under
  `docs/public/releases/` with the existing `xtask release` tooling, then
  verify the imported references, attribution, notes metadata, and release
  checks. No comparison range, changelog entry, contributor, or publication
  date is invented in this draft.
- Require the exact-source CI and Release CD gates before publication. Candidate
  and final releases have separate registry rules; neither a local build nor a
  draft note authorizes uploads.

An earlier combined strict Clippy run reported 471 denied diagnostics, largely
pre-existing browser-port lint debt. The current scoped native Python bridge
strict Clippy check passes. Keep the broader baseline separate in the
verification handoff and confirm the exact-source hosted lint gate before
calling source CI green.

The public `v0.1.2` notes provide the established format, but the
0.2.0 notes must be generated from the actual candidate or final GitHub
comparison export. This file remains a draft until the release owner records
the final source identity, verifies every required gate, and makes a separate
release decision.

## Existing commands for the release owner

The current source is locally consistent at 0.2.0:

```sh
cargo xtask bump-version 0.2.0 --date-released 2026-10-11 --check
```

After selecting a source ref available on GitHub, fetch its authentic comparison
against `v0.1.2`, then prepare the draft through the existing tooling:

```sh
cargo xtask release fetch 0.2.0 --repository CascadingLabs/Yosoi --previous-tag v0.1.2 --target-ref SOURCE_REF --output EXPORT.md
cargo xtask release prepare 0.2.0 --date 2026-10-11 --channel preview --previous 0.1.2 --github-notes EXPORT.md
```

`SOURCE_REF` and `EXPORT.md` are explicit inputs for that later run. No export or
canonical numbered note is fabricated here. Review the generated draft and its
attribution before finalizing it and running `cargo xtask release check 0.2.0`.
If the release date changes, synchronize it through the version helper first.
These preparation commands do not create a tag or publish packages.
