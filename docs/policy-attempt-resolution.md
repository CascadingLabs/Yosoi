# Policy attempt resolution

Status: implemented specification preparation for the Yosoi facade. Resolution
does not perform HTTP or browser I/O.

## Request and context

The caller keeps its Policy declaration, creates one
`PolicySnapshot::from_policy(&policy)`, and calls
`PolicyResolver::resolve(&snapshot, request, context)` for each attempt. A
`PolicyResolutionRequest` contains a fresh caller-allocated `CaptureId`, a
validated `RequestedWebTarget`, and one to three unique required families from
`Source`, `RenderedDom`, and `AccessibilityTree`. Empty, duplicate,
unbounded, or non-page evidence requests fail before a capture specification
is created.

The caller supplies one provider context that must match the policy's page
acquisition. A mismatch is a typed error; the resolver does not switch
acquisitions or retry with another provider.

Use `PolicyResolutionContext::direct_http(inputs)` or `::browser(inputs)` to
own the concrete provider input value. Their dispatch storage is boxed, without
changing the ordinary input structs or the policy declaration shape.

Direct HTTP context carries the existing acquisition strategy, accepted source
formats, unsupported-format behavior, retention choice, producer, operation,
and candidate output schemas. The resolver rejects profiles other than
Standard and sessions other than Isolated because the current Direct HTTP
executor does not support them. Network output schemas are pruned because
network evidence is outside this page-policy request surface.

Browser context carries the existing navigation context and completion policy,
rendering overrides, already-validated browser certification, producer,
operation, candidate schemas, activity-local identity plan, evidence-admission
policy, and settlement behavior. The policy supplies browser mode and bounds.
The resolver does not construct provider capabilities or invent a certified
browser profile. Existing browser-spec validation rejects a mode mismatch,
frame navigation, missing required capability, missing schema, or inconsistent
identity plan before I/O.
The concrete adapter supports event-driven `DomContentLoaded` and the existing
full-load `ControllerCompleted` mode. Standard execution selects full load when
any acquisition for that browser mode requests `ResponseDocument`, because the
main response body must finish before it can be retained. Exact DOM/AX-only
acquisitions use `DomContentLoaded`; they do not wait for network settlement or
the full load event. `LoadEvent` and `NetworkIdle` remain typed unsupported
modes. The resolver also checks the adapter's exact instrumentation subset:
Source or quiet-period collection needs network instrumentation, and
page-policy v1 never requests runtime diagnostics. These preflight rules must
track changes to the concrete adapter.

Candidate schemas are selected after required and optional evidence resolve.
Callers supply available schemas once; they do not repeat policy choices by
pre-pruning schemas. Required outputs without schemas fail through the
canonical spec constructor. Schemas for evidence the policy skips are removed
before that constructor runs.

## Evidence decisions

Caller-required evidence takes precedence over the policy's optional list.
When a family appears in both, the resolved spec requests it once as Required,
and AppliedPolicy records that the optional choice was promoted.

Direct HTTP requires Source explicitly. A caller-required DOM or accessibility
family is rejected before spec creation because Direct HTTP cannot provide it.
Policy-optional DOM and accessibility evidence are skipped for Direct HTTP and
recorded as unsupported by the selected acquisition. They are not silently
requested or substituted with Source.

For browser acquisition, each optional family is requested only when the
supplied certification reports it Supported. Disabled, unavailable, and
unsupported optional families are omitted and each receives a typed skip
decision. Required families are never skipped: a required capability failure
returns the existing browser-spec error.

## Bounds and identities

The snapshot identity is copied into AppliedPolicy without recomputation.
AppliedPolicy contains typed decisions and the exact numeric bounds resolved
into the capture spec. It does not retain the target URL, credentials, browser
handles, or captured source. The resolved engine spec necessarily carries the
target needed for later execution.

The shared maximum elapsed value becomes the existing observation deadline.
Direct HTTP source limits map independently to content-coded response bytes,
decoded representation bytes, and derived Unicode UTF-8 bytes.

For browser Source, the representation-byte limit maps to
`BrowserByteDomain::CdpDecodedBody`. Chromium has already removed content
codings from this body, so the content-coded source limit is not applied to it.
Rendered DOM and accessibility JSON use their own UTF-8 limits. Browser byte
bounds retain the current post-provider-materialization enforcement and
per-payload scope; they do not claim to bound Chromium's peak memory. Event,
resource, and accessibility-node limits map to their separate canonical
provider bounds.

Direct HTTP redirect target policy is converted to the engine's
`DirectHttpRedirectTargetPolicy` and travels beside
`ResolvedDirectHttpCaptureSpec` in `ResolvedPolicySpec::DirectHttp`. CAS399
execution must forward that exact value to the existing target-aware request
path. When Direct HTTP redirects are disabled, the target rule is inert.
The content-free explanation records Disabled or Follow with its exact hop
budget, and target admission when Follow is enabled.

## Output and boundary

`ResolvedPolicyAttempt` exposes the canonical Direct HTTP or browser spec and
its AppliedPolicy identity, decisions, and bounds. The resolver does not read
configuration files, create provider resources, execute navigation, or fabricate
capture outcomes. CAS399 consumes the prepared spec and owns actual execution.
