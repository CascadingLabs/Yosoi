# CAS-330 resolved browser specification and owned adapter contract

## Authority and scope

Authority: CAS-330 and the shared browser-acquisition execution plan, reconciled
with completed CAS-308 and the CAS-320 provider certification. The local authority
snapshot is `/tmp/cas330-linear-requirements.md`. Historical CAS-308/313 references
to persistent-profile certification or standalone CAS-310 soak are superseded:
this foundation uses fresh isolated contexts only; integrated process-tree soak
and production operating-envelope certification belong to **CAS-333**, before
**CAS-335**.

Chromium execution and factual observations belong to VoidCrawl. Capture identity,
intent, schema, provenance, admission, accounting, durable artifacts and bundle-last
finalization belong to Yosoi. The integration is direct in-process Rust; Python,
PyO3, MCP and service boundaries are not capture authorities. No provider trait is
introduced. This change adds no provider dependency, execution, or final
`WebCapture` construction. `ReadyForFinalization` is staging eligibility, not a
finalized bundle or a declaration that all requested families completed.

## Resolved input and capabilities

`ResolvedBrowserCaptureSpec` owns the exact `WebCaptureRequest`, request-family
set, output schemas, producer/operation, environment overrides, navigation policy,
observation policy, bounds and certified capabilities. Output construction consumes
that spec, rather than accepting a second independent capability declaration.
Only top-level navigation is accepted. Headless and headful are modes of the same
specification. Persistent profiles, attachment to ambient contexts, cookies/storage
capture, mutation/actions, fallback and extraction are out of scope.

Navigation completion and quiet settlement are distinct. The single maximum
elapsed bound covers the attempt; there is no additional navigation timeout.
`NavigationCompleted` alone is not a terminal. DOM-content-loaded, load, provider
network-idle and controller navigation completion remain separate policy choices.
Runtime policy enforcement is CAS-329 work, not demonstrated by these pure tests.

Certification implements the fresh-launched-page instrumentation matrix:

Network and Runtime escalation are independent. Normal enables both. Minimal has
four explicit effective modes: neither, Network only, Runtime only, or both.
Source status always follows Network; Runtime-only escalation does not require
Source or Network.

`Unavailable` remains an output category;
unknown attached-browser capability state is deliberately outside this launched,
fresh-context certification. Provider profile support and these explicit nine
states must agree. Optional unavailable/disabled/unsupported outcomes preserve
their category; required families must be supported at resolution. Cookies and
storage requests (including optional requests) are rejected pending policy semantics.

Every requested family requires a schema, and unrequested families cannot carry
one. Source also requires a distinct source-representation schema. Retained source
interpretation staging must declare a digest binding to the exact retained source
bytes. Later admission must still validate the actual CAS-324 typed evidence,
source lineage, schemas, artifact identity and payload integrity; a digest binding
does not itself validate arbitrary serialized interpretation content.

## Bounds and ownership

Requested source, DOM, AX, runtime and visual each require their own decoded-body,
DOM UTF-8, AX JSON UTF-8, runtime UTF-8 or PNG bound. The resolved bound-domain set
must equal exactly the domains implied by requested byte-bearing families; Source and
SourceRepresentation share the one CDP decoded-body domain. Bounds are nonzero, unique and
addressable. The certified collection path accepts only post-materialization
retention enforcement; it never promises streaming or peak Chromium/CDP memory
bounds. Per-payload and capture-aggregate scopes are explicit. Aggregate observation
byte/event limits constrain admission. Resource and AX-node counts are separate
from bytes. Layout is structured-only: its fixed viewport/content geometry records
cannot be staged as arbitrary serialized bytes. AX retained snapshots require a
reported node count within the bound; source/DOM/AX/visual payload mappings require
family-matched document scope, epoch, and observation offset.

`BrowserArtifactStaging` contains all nine families plus source interpretation.
Structured Network evidence owns validated resource admitted, retained, and
exact-or-unknown lost accounting; retained resources must equal its vector length and
admitted resources cannot exceed `max_resources`. Its ordered Network vector reconciles to that accounting, which must
be a subset of global observation accounting; global accounting may additionally
include console and Runtime events.

Each family is unrequested, complete, partial, truncated, discarded, unavailable,
failed, disabled or unsupported. Complete retains every observed byte; partial and
truncated preserve retained bytes, observed count, known/unknown loss and reason.
Discarded retains its domain, observed extent and reason but no payload. Failed
siblings do not erase successfully retained evidence. Slot validation rejects wrong
family mappings and discarded domains. Source representation shares the source/CDP
budget, including capture-aggregate sums. A ready retained source outcome requires an intact, complete source-representation
payload digest-bound to its retained source bytes. Unrequested, unavailable, failed,
disabled, and unsupported source/representation states must match. A discarded source
has no retained bytes, so its representation is ready only when explicitly unavailable;
this is the narrowest truthful pairing. Partial/truncated retained source still requires
complete bound representation. Mismatched categorical pairs and missing derived evidence
are not ready-finalizable, while stopped results preserve all staged evidence. Stopped captures may retain partial source evidence without
becoming ready. Facts validate request/capability agreement.

`BrowserStagingParts`, slot/staging `into_parts`, and borrowing accessors expose
owned payloads, mappings, measurements and reasons without live handles.
`BrowserAdapterFactsParts` transfers the spec, environment, staging, offset,
event/byte accounting, settlement, navigation and cleanup facts without losing data.
Invariant-bearing facts, mappings, staging and result fields remain private;
extracted parts are not a bypass around validated constructors.

Network staging owns resource records and receipt-ordered event facts, resource
and event loss, and a complete/partial reason. It checks resource bounds, unique IDs,
backward redirect references, event order, terminal offsets and event-accounting
agreement. Layout staging can own document-correlated layout/visual viewport and
content rectangles. Geometry uses integer micro-CSS pixels; CAS-329 must reject
unrepresentable provider values rather than silently round them. This is a bounded
layout primitive, not style/text-box/paint-order capture.

Frame IDs, resource IDs and document epochs are capture-local opaque identities,
not Yosoi artifact IDs or globally reusable browser handles. CAS-329 must consistently
translate provider frame/loader/epoch relationships into this scope. No claim is
made that this pure contract has exercised real frame migration or OOPIF behavior.

Byte accounting is derived with checked addition from every staged slot rather
than supplied as an unrelated aggregate. Unknown discarded extent contributes zero
to the measured observed lower bound and preserves unknown loss, never known zero
loss. Structured facts contribute no invented serialized bytes before admission;
network event retention/loss reconciles with the existing `EventAccounting` type.

## Terminal and cleanup semantics

Every resolved terminal preserves its occurrence offset, which must equal facts'
`observed_through`. Earliest offset wins; priority breaks ties only. Candidates at
or after the maximum normalize to deadline at the exact maximum. An explicit deadline
candidate always normalizes to the configured maximum, even if provider-supplied offset is
early; an earlier real stop still wins.
Tie order is deadline, system interruption, caller cancellation, cleanup failure,
provider failure, event limit, byte limit, quiet settlement, controller completion.
Same-category ties retain input order, so adapters must preserve receipt ordering.

Ready requires completed navigation and cleanup, and either controller completion
with settlement disabled or quiet settlement with matching validated evidence.
Quiet evidence must match policy ID, terminal offset, required duration and in-flight
threshold. Stopped rejects successful terminals. A cleanup-failure terminal requires
failed cleanup; an earlier stopping terminal may retain later failed cleanup without
rewriting the winning terminal. No result can be constructed with public enum fields
to bypass these checks.

Provider cancellation maps to caller interruption only when caller initiation is
known; explicit provider interruption requires the adapter to retain caller/system
attribution. Finished observation/controller return is not proof of quiet settlement.
Provider disconnect, page/renderer/navigation/internal/cleanup failure and event/byte
limits have distinct typed vocabulary. CDP decoded response bytes are **not**
content-coded wire bytes; encoded transfer lengths are separate resource metrics.
Unavailable ExtraInfo, redirects without bodies, cache/service-worker gaps and
unreported loss must remain explicit rather than reconstructed from DOM or headers.

## Closed provider mapping checklist for CAS-329

The following is the semantic mapping authority, not an assertion that dependency-
linked conversion functions have been implemented. CAS-329 must use exhaustive
Rust matches against the selected revision, not `Display` parsing or property bags.
New upstream variants require review; the pre-release native API is not frozen.

| Provider vocabulary | Yosoi staging meaning |
| --- | --- |
| `CapabilityState::{Supported,Unavailable,Disabled,Unsupported}` | corresponding explicit capability category; unavailable attached state is rejected by fresh-launch certification |
| `EnvironmentObservation::{Known,Unavailable,Omitted}` | `EnvironmentValue` known/unavailable/omitted, preserving typed reason attribution |
| unavailable environment: attached-not-controlled, browser-did-not-report, invalid-value | distinct namespaced reason codes; no inferred override-as-observation |
| omission: minimize-instrumentation, sensitive-value | distinct omission reasons, never observed empty values |
| decoded body, DOM UTF-8, AX JSON UTF-8, runtime UTF-8, PNG | corresponding `BrowserByteDomain`; byte spec domain/scope/enforcement retained |
| recording frame, encoded recording | rejected outside this specification, not mapped to PNG |
| streaming admission, retention after materialization | closed enforcement vocabulary; only latter certified for this path |
| per-payload, aggregate | corresponding bound scope |
| measured bytes known / provider-not-reported / capture-ended-early / not-applicable | exact count / unknown extent, with provider reason retained at conversion boundary |
| complete, truncated, discarded, unavailable, failed payload extent | matching staging category; partial observation scope remains partial separately |
| payload unavailable: provider-not-reported, not-collected, unsupported | unavailable / unrequested only when intent agrees, otherwise unavailable / unsupported only when certification agrees |
| payload failure: provider-rejected, disconnected, invalid-encoding, deadline, cancelled, sink-failure | failed family with distinct reason; attempt terminal resolved independently from timed signals |
| resource pending, response-received, redirected, complete, failed(cancelled,blocked) | exhaustive `BrowserResourceOutcome` variants |
| all seven observation event kinds | one-to-one `BrowserObservationKind`, preserving receipt sequence and offset |
| navigation finished / observation finished | controller completion candidate, never quiet evidence |
| cancelled / interrupted | caller cancellation / explicitly attributed caller or system interruption |
| deadline, event-limit, disconnected | corresponding timed terminal candidate |
| source request-failed, CDP-body-unavailable, invalid-base64, capture-ended-before-body | unavailable source with distinct reason; no DOM substitution |
| ExtraInfo unavailable in current client | no raw Cookie/Set-Cookie/header fidelity claim |
| known dropped count / not-collected / provider-not-reported | known loss / explicit unknown loss; never fabricate zero |

Error dispatch is also categorical: launch/connection/Chromium-acquisition failures
are provider setup failure; navigation failure is navigation failure; page/JS failure
is page or affected-family failure; screenshot/body failures affect visual/source
families without erasing siblings; browser-closed is disconnected. Navigation/general/
response timeouts imply an overall deadline only at the resolved bound, otherwise
navigation/provider failure. Session-interrupted requires explicit initiator evidence.
Invalid input and invalid/duplicate/not-owned/missing/expired/terminal interrupt requests
are adapter/provider internal failures, not caller cancellation. Frame-not-found or
ambiguous-frame is unavailable scoped evidence. PDF, recording/encoding, element/
selector/visual-target actions, managed-profile errors and challenge-routing errors
are outside the requested acquisition surface and fail closed if returned unexpectedly.
Legacy `Other` is internal failure with a safe reason, never parsed diagnostic text.

Byte families use complete/partial/truncated/discarded payload states. Structured
network/layout use complete or partial owned facts; structured loss is record/event
loss, not invented truncated serialized bytes. Unrequested and categorical unavailable/
failed/disabled/unsupported states are common, subject to request and certification.
Cookies/storage cannot produce retained evidence in this foundation. Any future
structured discard/truncated serialization semantics require an explicit admission
contract rather than assigning them a provider byte domain.

## Dependency, runtime and integration plan

`void_crawl_core` is not on crates.io. CAS-329 adds an exact Git `rev`, never a branch
or floating tag. The previously recorded candidate
`c1cba0dc196dc66b8c188b2e465e237b7cabdbad` is provisional, not a verified pin from this
change. Provider-first changes may replace it. Both inspected workspaces declare
Rust 1.98, edition 2024. The intended dependency uses `default-features = false`;
core currently declares no default features. CAS-329 must verify its exact revision's
feature/MSRV surface and migrate all affected Rust/binding consumers when needed.
All Rust/Python/PyO3/MCP surfaces remain pre-release with no customer compatibility
commitment; bounded breaking changes are allowed and must be recorded together.

Checkout-local development may patch the exact Git source through untracked
`.cargo/config.toml`. Integration verification must disable that override, build the
exact revision in a clean target and rerun tests and warnings-denied Clippy. A patched
checkout pass is not pin verification. No such integration verification occurs here.

Conservative provisional runtime policy: one attempt at a time, one explicitly
owned launched browser process and fresh disposable context per attempt, headless
unless requested headful, 10 seconds per attempt, 4096 events, 512 resources, 10000 AX
nodes, 8 MiB each source/DOM/AX/PNG and 64 KiB runtime diagnostics. These are proposed
CAS-329 runtime inputs, not implemented defaults or an operating-envelope guarantee.
No pool, recycling, throughput or memory guarantee precedes CAS-333.

Direction: `de1cee33-b090-43a0-ab72-a8ef6c32a296`.
CAS-330 WorkUnit: `ba8a62f7-f9c3-451f-ba5a-1d350f54271d` (default-workspace scoped;
parent records authoritative checkpoints). Physical workspace:
`/home/andrew/Desktop/cl/yosoioxide-cas-330-contract--YosoiOxide`, JJ change
`upypwttz`; sole CAS-330 mutation owner. WTF owns workspace/environment setup;
JJ owns change topology. No other workspace or repository is modified.

At most two mutation lanes: provider-first VoidCrawl, then Yosoi adapter/pin.
CAS-329's integration owner owns the pin, manifests/lockfile, reexports and clean
paired verification; provider owner owns core mechanisms and corresponding binding
migrations. CAS-333 owns integrated soak, then CAS-335 consumes certification.
Create separate repository-scoped WorkUnits for those issues before mutation;
the snapshot supplies no UUIDs or human assignees for them, so none are invented
here. Checkpoint at contract decision, provider landing, pin update, clean test
verification and handoff. Shared manifests, reexports and fixtures have one writer
per lane; disjoint read-only review can proceed independently.
