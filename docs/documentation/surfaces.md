# Surface capability design and delivery plan

**Review draft. Not an approved production API or a release candidate.**

[Linear design draft](https://linear.app/cascadinglabs/document/draft-surfaces-rustpython-sdks-cli-web-and-video-6947551a5e9e) · [Review issue CAS-616](https://linear.app/cascadinglabs/issue/CAS-616/review-and-shape-surfaces-across-rust-python-and-cli)

This PR implements Surface readers in Rust, Python and the CLI. Python bindings, public guides, installed-artifact examples and expanded parity evidence are being completed under CAS-619. The browser-control adapter remains a separate integration boundary. R2 was clarified as a typo; there is no Cloudflare R2 storage requirement.

## Review entry points

- [Shared DTOs and SurfaceRead](../../crates/yosoi/src/surface/model.rs)
- [Immutable web reader](../../crates/yosoi/src/surface/web.rs)
- [Video reader and native processing](../../crates/yosoi/src/surface/video/mod.rs)
- [Agent CLI and web authority boundary](../../crates/yosoi/src/bin/yosoi/surface_command.rs)
- [CLI recording and repeat](../../crates/yosoi/src/bin/yosoi/surface_command/README.md)
- [Two-surface guide and limitations](../../crates/yosoi/src/surface/README.md)
- [Cross-provider native tests](../../crates/yosoi/tests/surface_two.rs)
- [Python facade](../../python/yosoi/surface.py)
- [Python installed-artifact tests](../../python/tests/test_surface.py)
- [Public Surface guide](../public/concepts/exploring-a-surface.md)

The older independent sidecar lab has been removed. SDK and CLI implementations live in their normal crate modules; there is one implementation to maintain. Private `.local` recordings, screenshots, decoder outputs and Archive stores are excluded from the PR.

## What the spike established

- Shared bounded describe/read/reference contracts can serve web documents and video timelines.
- Live web reports `controllable: true`; immutable video and archived evidence report false. This flag is descriptive; runtime authority and target eligibility remain separately enforced.
- Web actions preserve current-document checks, hit testing, explicit hot ownership and observed postconditions.
- Video navigates intervals lazily and produces real PNG frames/crops with measured source PTS, stream-relative time and explicit decoded pixel coordinates.
- Existing Archive Documents and AutomationRecords can retain/reopen source and derived evidence without restoring browser/device authority.
- Offline evidence reconstruction and fresh live execution are distinct operations.

Local spike evidence before this draft handoff: 22 Rust tests (18 existing plus four cross-provider/native-media tests); 39 legacy web CLI checks; both supplied recordings each passed 17 web and 16 video replies; selected saved pixels reopened with originals removed and browser/decoder paths unavailable; the live docs version menu completed Latest → v0.1.0. These results are not production browser certification, exact-head hosted CI, Python parity or a general performance guarantee.

## Production decisions left open

- Public Rust/Python/CLI contract, schema evolution and ownership/cancellation semantics.
- Integrate the established browser/session/provider stack. ChromeDriver is an experimental adapter, not a production controller decision.
- Source-specific versus common session state; capability absence and typed errors.
- Frame selection: the prototype's at-or-after sampling can explicitly return no frame in the final-frame tail.
- Decoder profile compatibility, sparse coverage, estimated duration and coordinate transforms.
- Binary artifact storage: prototype base64 JSON envelopes add overhead.
- Recording policy/checkpoints: immutable full-record rewrites after each command are not a scale claim.
- Compatibility for existing captured references/records and removal of duplicate lab code.

No TV, game, drone, live camera, OCR, ASR, semantic video search or universal device-action implementation is proposed here.



## Draft implementation tickets

| Ticket | Review scope |
| --- | --- |
| CAS-616 | Coordinate draft review and production decisions |
| CAS-593 | Shared contract and Rust facade |
| CAS-617 | Web provider, using the web experiments |
| CAS-618 | Video provider, inspired by FlameFrame |
| CAS-619 | Python `ys.surface` parity over Rust |
| CAS-620 | CLI protocol and lifecycle |
| CAS-621 | Production Archive recording/replay in Archivable Automation |
| CAS-598 | Cross-surface / cross-interface acceptance |

CAS-619 is Agent Working following Andrew's explicit request to complete both SDKs, docs, CLI and live testing. Existing CAS-594/595/596/597/599/600 remain linked foundation work, not silently replaced or closed. Completion still requires installed examples, the expanded parity ledger, rendered docs and hosted checks for the final source.


## Full review brief

<!-- linear:callout icon=Lightbulb -->
> [!NOTE]
> **Plain English**
>
> This is a draft for Andrew to review later. Give callers one bounded way to inspect evidence through Rust `ys::surface`, Python `ys.surface`, and the CLI, starting with web and video. A surface says whether it is controllable, while actual control still requires live authority and eligibility.

## Status and intended decision

Draft / shaping, not an approved production API or a claim that the spike is ready to land. Preserve the experiment for review and use these tickets to decide what to carry into production.

Rust and Python now share the immutable index, web read protocol, video provider, image regions, cursor/session ownership and normal Archive source/frame storage. Python semantic parity is under active verification, not yet a completed gate. “R2” was clarified as a typo; no Cloudflare R2 integration is included in this scope.

## Direction

A source provides evidence. A surface makes a representation of that evidence addressable under a budget. Observations are immutable. Sessions own cursor position, subscriptions and live authority. Capability implementations remain representation-specific.

Shared model:
- Source, surface and observation identities are distinct.
- References carry an observation identity and producer-owned opaque address.
- Descriptors expose `controllable: true/false` and actual capabilities.
- `controllable` describes the currently bound provider, not a permission or restored action lease.
- Shared reads cover bounded overview, inspection and supported expansion/search/parent operations. Unsupported operations must fail explicitly; video does not invent text search or a universal parent.
- Budgets apply to complete serialized responses, including envelopes and continuations. Binary evidence has separate byte/pixel/duration/processing limits.
- Provenance, interpretation version, source coverage, omitted results and uncertainty remain explicit.
- Captured references never silently become live targets, and archived data never restores hot authority.

Do not build TV, game, drone, live-camera, audio, OCR, transcription, or a universal device-action language now. Use those domains only to challenge boundaries. Additional providers follow concrete workflows.

## First supported use cases

### Web

Inspiration is the web experience from this spike: live DOM exploration, the large QScrape fixture/freshness work, CNN visibility/occlusion lessons, and the Yosoi docs version switch. “Experience” was clarified to mean these experiments, not a separate external product.

Acceptance journey: open the current “What is Yosoi?” page, find the documentation release control from surface evidence, open Latest, choose v0.1.0, and verify the resulting version and visible overview fallback. Use a controlled local equivalent in required tests; the live public site is supplementary evidence.

Keep web source control capability separate from immutable web observations. Production must integrate the established Yosoi browser/session/provider stack; the spike's ChromeDriver adapter is experimental evidence, not a replacement or a certified provider.

### Video

Take inspiration from FlameFrame's process / timestamp / inspect / zoom evidence-pack workflow. Start with local immutable video files and visual timeline/frame/crop access.

Acceptance journey: open a recording, explore bounded temporal intervals, request a frame, inspect a crop with explicit pixel coordinates, retain requested time separately from measured PTS and stream-relative time, archive the source and actual pixels, remove the original input copy, and reopen evidence with decoder and browser paths unavailable.

Audio-stream metadata is not audio observation. Without actual OCR/transcription, text search of video content is unsupported. Do not claim all frames were observed from a timeline index or selected samples.

## SDK and CLI delivery

- Rust: `use yosoi as ys;` and the public `ys::surface` namespace.
- Python: `import yosoi as ys;` and `ys.surface`, backed by the same Rust behavior through the existing binding architecture.
- CLI: explicit web/video providers, shared describe/read/reference protocol, source-specific capabilities, bounded structured replies and persistent-session lifecycle.
- Parity covers values, identity, limits, errors, unavailable capabilities, cancellation, cleanup, recording policy and artifacts—not just similar method names.
- A live web provider can be controllable; an immutable video snapshot or archived view is not.
- Retain private runtime permits and provider handles outside serialized DTOs.

## Recording and replay

Use the existing Archive and AutomationRecord foundations. Define recording as an explicit policy, with source and derived-evidence retention limits and declared checkpoint semantics.

Distinguish:
1. offline reconstruction / inspection: no live control;
2. repeated live web execution: a new session, fresh references, revalidated eligibility and observed postconditions.

Record action rejection, dispatch uncertainty and postcondition results separately. A native call returning successfully is not business success.

The spike uses versioned JSON envelopes around binary video/PNG evidence and rewrites immutable checkpoints after commands. These are prototype choices to review; decide the production binary artifact format and write-amplification policy before promising scale.

## Evidence available from the spike

Local functional evidence, not production or hosted-CI certification:
- 18 existing Rust surface checks plus 4 cross-surface/native-media tests passed.
- Both user-provided recordings passed end-to-end CLI runs, each with 17 web and 16 video replies.
- 39 existing web CLI interaction checks passed.
- Video frames/crops reopened offline after removing the input copy and disabling browser/FFmpeg/FFprobe executable paths.
- A synthetic nonzero-origin video distinguishes requested 1.25s, decoded stream-relative 1.5s, and source PTS 6.5s.
- Live docs Latest → v0.1.0 still completed two confirmed clicks through the CLI.

Private recordings, screenshots, raw archived evidence and local `.local` artifacts are not publication assets. The draft PR preserves reproducible source and synthetic/native verification drivers.

## Open production decisions

- Final public DTO/error/capability vocabulary and schema evolution.
- Ownership of session state versus immutable readers; one cursor first, multiple cursors deferred.
- Event coverage, scoped freshness and cancellation across capture/inspect/action.
- Frame-selection policy: the spike samples at-or-after and explicitly reports missing final-tail frames.
- Snapshot-copy/source-size limits, media decoder compatibility, time-base precision and scaling/crop coordinates.
- Binary evidence storage and checkpoint frequency; avoid growing full-record rewrites on every read.
- Python ownership/async/cancellation behavior and common Rust/Python/CLI acceptance vectors.
- Migration of prototype native web references and command recordings without silently changing meaning.

## Existing foundation tickets

CAS-593: shared Surface interaction contract and Rust foundation.
CAS-594: structural reduction for the existing document representations.
CAS-595: exact observation-bound references and source-backed inspection.
CAS-596: complete-response budgets, omissions and progress-safe continuation.
CAS-597: reusable task-independent preparation and ownership.
CAS-598: cross-surface and cross-language acceptance matrix.
CAS-599: large live QScrape freshness and scenario design.
CAS-600: optional multiple readers and one hot owner after the single-cursor foundation.

The document-specific corpus remains useful substrate. It does not force video into a DOM or make every provider support every read.

## Review order

Shared contract → web and video vertical slices → Python and CLI parity → production recording/replay integration → acceptance and measured limits. Keep initiative order Surfaces foundation → Archivable Automation → Discovery. No model/runtime vendor defines the shared contract. No production dates, estimates or landing approval are implied.
