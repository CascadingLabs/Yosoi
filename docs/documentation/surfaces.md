# Surface architecture and review

Surface separates immutable evidence, live authority, provider execution and transport.
The shared contract is bounded evidence navigation. A DOM node, a timeline interval
and a pixel rectangle keep their provider-specific meaning; none becomes a universal
coordinate or action permission.

[CAS-616](https://linear.app/cascadinglabs/issue/CAS-616/review-and-shape-surfaces-across-rust-python-and-cli)
owns the observation SDK. Portable policy archives belong to the dependent CAS-621
change. Browser-provider integration remains CAS-617. No device, TV, game or drone
provider is implemented by this change.

## Dependency direction

```text
CLI arguments / JSON-lines / signals
                  |
          Surface connection
          /
   web execution     video execution
        |                  |
 session + web reader   video reader + decoding
          \              /
      shared read DTOs and budgets
```

The CLI dispatches browser and video connections. Shared connection code does not
read stdin, write stdout or install process signal handlers. This lets a caller own cancellation and transport.
Live repetition reports each confirmed iteration through a callback, preserving
progress if a later iteration fails.

The index is pure and independent of browser launch and OS APIs. Providers own
capture, addresses, eligibility, side effects and resource cleanup. A new modality
implements the existing read boundary and advertises its actual capabilities.
It need not support search, parents, pixels or control. Add source dispatch only
when a real provider exists; do not add speculative device enums or a plugin registry.

## Why each implementation file exists

Paths below are relative to `crates/yosoi/src/surface/`.

| File | Responsibility and boundary |
| --- | --- |
| `mod.rs` | Document index, native document references, resource bounds and bounded navigation. No live browser ownership. |
| `prepare.rs` | Parses supported Document representations and applies consistent structural reduction. One normalization boundary for every document input. |
| `model.rs` | Representation-neutral identities, descriptors, read requests/results and `SurfaceRead`. Addresses stay opaque. |
| `browser/document.rs` | Projects the document index onto the shared read contract and translates exact native references. An immutable reader, with no action authority. |
| `session.rs` | Shared capture history, independent cursors, region watches and the single hot action lease. Owns revocation and freshness, not browser commands. |
| `images.rs` | Checked pixel rectangles and bounded image materialization. Pixel coordinates never become document references. |
| `video/mod.rs` | Frozen video ownership, metadata, decode policy and frame/crop materialization. No browser dependency for standalone video reads. |
| `video/timeline.rs` | Lazy temporal addresses, interval subdivision and bounded read continuations. Isolates timeline semantics from native processes. |
| `video/process.rs` | Bounded FFmpeg/FFprobe subprocess output, deadlines, kill and reap. This is the native processing boundary. |
| `video/archive.rs` | Existing Archive integration for frozen source and decoded PNG evidence. Loading evidence never launches a browser or restores hot authority. |
| `browser/mod.rs` | Browser reader and connection entry points. |
| `policy.rs` | Source-independent archive selection, output paths and execution errors. |
| `connection.rs` | Generic connection lifecycle, command bounds and trace checkpoints; no provider enum or process code. Shared JSON command contract; no terminal or OS signal ownership. |
| `browser/session.rs` | Live web command handling, exact-reference validation, action leases and observed postconditions. |
| `browser/process.rs` | ChromeDriver transport and isolated profile lifecycle. Reuses shared platform discovery and Stable browser admission. |
| `browser/extract.js` | In-page DOM capture, eligibility/hit testing and postcondition observation. Browser-only code stays at this boundary. |
| `video/session.rs` | Read-only video execution using the shared command protocol. Rejects live web/control commands. |
| `archive.rs` | Existing Document/AutomationRecord checkpoints and offline reconstruction. The dependent Archive PR replaces private handles with first-class policy archives. |
| `browser/archive.rs` | Browser-specific capture, finalization and procedure replay. |
| `browser/archive/repeating.rs` | Fresh-session execution of saved intentions, including complete search and unique eligible target resolution. Separate from offline replay. |

These files correspond to distinct evidence, authority, process or persistence
boundaries. Further splitting should follow ownership, not the number of methods.
`src/bin/yosoi/surface_command.rs` contains only application wiring: Clap arguments,
bounded JSON-lines framing, terminal replies, input cancellation and shutdown.
Acceptance drivers live under `tests/fixtures/surface_cli/`, outside the binary.

## Operating systems

The web adapter uses Yosoi's existing executable discovery and supported Stable
admission rather than a Linux executable path. It does not force an X11 backend.
ChromeDriver selection remains explicit through `CHROMEDRIVER` or the system PATH;
`CHROME` can select an installed supported browser. Sandbox and process isolation
remain enabled. Platform discovery is shared infrastructure, not a new Surface trait.

Video subprocesses use Tokio process APIs and provider-owned executable/policy
settings. OS differences stay below the provider boundary. Cross-platform source
structure does not establish Windows/macOS browser certification; those need their
own execution evidence.

## Review and validation

The public [Surfaces guide](../public/concepts/surfaces.md) combines document and
video exploration and teaches a coding agent to add the Arc desk lamp at QScrape
eShop without CSS/XPath selectors. The [CLI guide](../public/cli/surface.md) documents
the transport. Python exposes the root `ys.Surface` spelling and delegates index
behavior to Rust.

Keep these evidence levels separate:

- `tests/surface.rs`: document formats, structural reduction, budgets, references,
  cursor state, watches and authority.
- `tests/surface_two.rs`: shared web/video behavior, actual decoding, pixel bounds,
  frozen source identity and Archive restoration.
- `tests/fixtures/surface_cli/verify*.mjs`: real browser and CLI acceptance stories,
  recording, repetitions and offline reconstruction.
- `python/tests/test_surface.py` and `scripts/sdk-parity/`: installed bindings and
  explicit Rust/Python mappings. Generated snapshots are data, not executable LOC.
- Current-head hosted CI and live QScrape execution: distinct from local checks.

## Parity inputs and generated evidence

`python/parity/surface-contract.json` is the single reviewed Surface input. It
stores Rust signature pins, Python target/shape pins, argument conversions and
explicit language-specific exceptions. Existing contract/ledger files reference
it; the loaders derive the two gate inputs without storing duplicate mappings.
Standard Rust trait mechanics use the reviewed policy already defined in tooling.

CI still builds the Rust compiler inventory, introspects the installed Python
package, checks API drift and runs shared behavior vectors. Full inventories,
source keys, runtime ledgers and result reports belong to CI artifacts. Generated
runtime ledgers are self-contained; replaying their validation does not depend on
an adjacent source contract. `build_surface_contract` converts a full report and
its explicit ledger mappings back into the compact review input; it never guesses
mappings or approves exceptions.

Count handwritten implementation, tests/docs and parity inputs separately. Keep
all signature pins and behavior assertions when reducing duplicated metadata.
