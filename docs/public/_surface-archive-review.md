# Portable Surface Archive review

This is a maintainer receipt, excluded from public pages.

Workspace: `/home/andrew/Desktop/cl/yosoi-surface-policy-archive`.
Draft stack: [PR #167](https://github.com/CascadingLabs/Yosoi/pull/167), based on
[PR #164](https://github.com/CascadingLabs/Yosoi/pull/164).

## Claims and evidence

| Claim | Source and verification |
| --- | --- |
| Policy retains an archivable outcome | `surface/session.rs`, `surface/outcome.rs`; Rust policy/history/lease tests and installed Python acceptance |
| Existing Archive callable handles outcomes | `archive/surface.rs`; typed Rust/Python round trips and compiled Plan retention |
| One file survives removal of the original directory | `archive/portable.rs`; moved-file tests, fresh process, six cross-SDK representation cases, and live docs evidence |
| Import validates bounds, versions, digests and dependencies | Corrupt, truncated, unsupported-schema, oversized and missing-dependency acceptance |
| SDK and CLI share execution | `surface/runtime`; public native wrappers and transport-only CLI; preflight and interruption tests |
| Rerun creates fresh authority and evidence | Live docs version story followed by separate Rust/Python reruns; original file hash unchanged |
| Video pixels need neither original source nor FFmpeg on reload | Both supplied recordings; three saved pixel artifacts replayed three times after removing their temporary stores/input copies, with executable paths disabled |

## Exact lesson programs

The three Rust and three Python fences in `concepts/archiving-a-surface.md`
were extracted unchanged to `.local/doc-snippets/source`. Save and reload printed
`v0.1.0` and one match with sealed/complete outcomes. Each live rerun program
loaded the moved docs archive and wrote a separate portable result.

The existing CascadingLabsFE pipeline selected this workspace explicitly.
The lesson is in Concepts navigation. A regular Chrome 156 / matching driver
session followed the index to the Python tab and confirmed visible Python code.
The screenshot and 29-reply transcript are in `.local/doc-preview-browser-2`.
This is local preview evidence, not documentation deployment.

## Boundaries retained

Archive is opt-in and bounded. `sealed` means finalization, not task success;
`complete` means required evidence was retained, not that source coverage was
complete. Rejected, failed and unknown outcomes remain inspectable and savable.
Loading evidence grants no live authority. Rerun uses fresh observations,
unique eligible targets and explicit postconditions; it does not simulate saved
JavaScript or restore browser memory. The existing Unix Archive certification
boundary remains. No release, merge, deployment, cloud backend, new selector
language or additional device provider is included.

## Delivery checks

Compiler-derived references are generated from an immutable stack revision;
Python reference source and fields are inspected separately. Hosted checks are
followed on the exact child head and intended Surface parent. Final status and
source identities are recorded in the PR and private delivery audit.
