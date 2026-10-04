# Policy ownership

Status: current ownership contract for passive policy values and per-attempt
capture preparation.

## Declaration, snapshot, and attempt

The application owns a Policy declaration as ordinary data. Policy contains
only the page acquisition/evidence choices and the request's shared deadline,
typed byte/event/count limits, and Direct HTTP redirect rules.

For an attempt, the caller passes a borrowed declaration to
PolicySnapshot::from_policy. The constructor validates the declaration,
computes its versioned effective identity, and clones it into an immutable
snapshot. The caller still owns its original Policy and may construct a
replacement value independently.

PolicyResolver::resolve borrows that snapshot plus a caller request and
execution context. It returns a resolved canonical capture specification with
its AppliedPolicy identity, decisions, and quantitative bounds. The caller can
inspect the prepared values, then consume them once with
ResolvedPolicyAttempt::execute. Execution does not consult another Policy,
environment file, global registry, or runtime policy pointer.

The ownership sequence is:

    caller-owned Policy
            |
            v
    immutable validated PolicySnapshot
            |
            v
    resolved attempt spec + AppliedPolicy
            |
            v
    Direct HTTP or browser execution

## Process-level state

The Yosoi facade is not a long-lived policy runtime. An unbound page request
uses the package's current `Policy::default()` when `send` prepares it; a bound
page request borrows one complete caller-owned Policy. There is no process-wide
current Policy, Policy::bind, PolicyTarget bridge, PolicyBindError, policy
merge, or per-invocation overlay.

The approved Requests interface keeps process ownership explicit:
`request.bind(&policy)` borrows the declaration, and preparation creates the
owned `PolicySnapshot` used by the response and every attempt outcome. A
long-lived application may store and replace its own Policy values, but Yosoi
does not provide a mutable registry or replacement protocol.

## Outcome ownership

AppliedPolicy is a content-free explanation of the snapshot values used during
resolution. It exposes the stable policy identity, typed evidence/acquisition
decisions, and exact bounds. It does not retain the target URL, credentials,
profile handles, or page bytes.

ResolvedPolicySpec carries the validated request target and engine inputs
needed for execution. Successful capture outcomes carry the canonical
CaptureBundle; Direct HTTP additionally retains its complete DirectHttpCapture
response and source facts. Policy identity is distinct from the fresh capture
occurrence and from artifact identities in provenance.

## Breaking boundary

The CAS397 Policy::bind(target) API and its PolicyTarget/PolicyBindError bridge
are removed. Callers now retain the declaration and create a snapshot by
reference. This keeps policy construction independent of a runtime target and
leaves process-held ownership to the Requests consumer that needs it.
