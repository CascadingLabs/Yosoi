# Policy SDK Zero decision and current boundary

Status: the CAS395 authoring shape and CAS396 policy values are implemented.
The former CAS397 runtime-binding bridge is removed. Policy values are passive
data; process-level ownership belongs to a consuming Requests project.

## Plain English

An application creates a complete policy value, keeps it as its own declaration,
and makes an immutable validated snapshot for each capture attempt. The resolver
maps that snapshot and caller intent into the existing Direct HTTP or certified
browser specification. The prepared specification is executed once and retains
its policy identity and content-free decisions.

## Authoring and execution shape

    use yosoi::prelude as ys;

    let page_policy = ys::policy::Page {
        acquisition: ys::policy::Acquisition::DirectHttp,
        optional_evidence: vec![],
    };
    let request_policy = ys::policy::Request::default();
    let policy = ys::Policy {
        page: page_policy,
        request: request_policy,
    };
    let snapshot = ys::PolicySnapshot::from_policy(&policy)?;
    let prepared = ys::PolicyResolver::resolve(&snapshot, request, context)?;
    let capture = prepared.execute(&cancellation).await?;

Page and Request are ordinary Rust values. PolicySnapshot::from_policy borrows
the declaration, validates it, computes its stable identity, and owns a clone.
The declaration remains available for application-level reuse or replacement.

There is no Policy::bind method, Yosoi runtime policy carrier, merge, layer,
global registry, chain, or per-call override. The caller decides who owns the
declaration and snapshot. Execution receives only the prepared attempt; it does
not reread configuration or policy.

## One owner per decision

| Decision | Owner |
| --- | --- |
| Target and required page evidence | Caller request |
| Direct HTTP / headless / headful | Policy.page |
| Optional page evidence | Policy.page |
| Shared deadline and domain-specific bounds | Policy.request |
| Direct HTTP redirect hop/target rules | Policy.request |
| Browser navigation, certification, and evidence admission | Existing browser capture context/spec |
| Output schemas, producers, and operations | Caller/execution context |
| Effective values used during work | Immutable resolved attempt spec |
| Status, availability, partial/failed facts | Capture outcome |
| Business meaning and field descriptions | Contracts |
| Candidate-record grouping | Extractor |
| Persistence and evidence lifetime | A named storage workflow, if one exists |

Required evidence wins over the same family in the optional list. Direct HTTP
requires caller-required Source and rejects caller-required DOM or AX before
I/O. Optional DOM and AX under Direct HTTP are recorded as skipped rather than
substituted. Browser required capabilities fail through the existing validated
browser spec; unsupported optional evidence is not attempted.

The policy byte values map to their real domains. Browser Source uses the
already-decoded CDP response body bound and does not claim a content-coded-byte
limit. Browser byte enforcement remains post-provider-materialization; it is
not a Chromium peak-memory guarantee.

## Snapshot and identity

The snapshot carries the validated immutable Policy clone and the deterministic
effective-policy identity. AppliedPolicy records that identity, typed decisions,
and the exact bounds wired into the spec. It contains no target URL, credentials,
browser handles, or captured source. A prepared spec contains the target needed
for execution and is intentionally a different value.

The policy identity is not a capture-occurrence identity, storage reference, or
business-record identity. Each caller allocates a fresh capture occurrence.
Artifact provenance and the final capture bundle remain the authority for
observed outcomes.

## Deferred integration gates

CAS400's Contracts/Extractor integration waits for CAS393's domain and locator
handoff. CAS401's combined certification waits for CAS394's certification
evidence. The successor briefs are planning only; they do not unblock those
gates or approve product APIs. In particular, Storage receives no policy fields
until a concrete owner, durability requirement, lifetime, and retrieval
workflow are supplied.
