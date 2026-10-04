# CAS-335 browser enhancement handoff

## Purpose and ownership

This handoff defines the next project after the fresh, disposable browser foundation (CAS-329–335). It adds managed profiles, profile leases, cookie/storage operations, operator orchestration, and later sessions/actions without weakening the capture and evidence boundaries already established.

**VoidCrawl owns reusable browser mechanisms:** launching/attaching an explicitly owned browser, creating and closing contexts, profile-directory mechanics, cookie and storage protocol calls, navigation/input primitives, action execution, cancellation, and provider-reported lifecycle facts. These mechanisms must be typed and expose no live provider handles to Yosoi.

**Yosoi owns policy and durable semantics:** authorization, profile identity and scope, lease admission/expiry, concurrency, budgets, action/session state machines, secret handling, provenance, audit records, idempotency, durable artifacts, and terminal/failure meaning. Yosoi must not infer browser state from provider diagnostics or make browser protocol calls directly.

The integration remains an in-process Rust adapter with an exact VoidCrawl dependency revision. No Python, MCP, service, or ambient-browser boundary is an authority.

## Inputs and outputs

A managed operation input contains an operation ID and producer/version, authenticated operator intent, profile reference and requested scope (`ephemeral`, named managed profile, or explicitly attached external profile if later approved), lease request, browser mode/environment, target/navigation policy, ordered session/action plan, cookie/storage selectors and mutation values, requested observations, resource/elapsed/event/byte limits, and an idempotency key. Secrets are references to an approved secret store or write-only inputs; they are never ordinary log fields or durable action JSON.

The adapter receives a resolved, policy-approved plan and returns owned provider facts: browser/context/profile identity (non-secret), lease-bound lifecycle events, ordered action results, navigation/session observations, cookie/storage operation receipts with redacted metadata, cleanup status, and typed failure/terminal facts. Yosoi then emits a durable operation record and, where requested and valid, the existing browser evidence/artifact bundle. Outputs must distinguish requested, completed, unavailable, failed, cancelled, expired, and not-executed work; a failed action does not silently become success or erase prior evidence.

## Smallest useful deterministic fixture

Provide one local fixture origin with deterministic endpoints and no external network dependency:

1. `/state` returns a counter plus the current cookie and local/session-storage values;
2. `/set` writes one fixture cookie, one local-storage key, and one session-storage key;
3. `/clear` removes them; and
4. `/echo` records a supplied action value and returns it.

The fixture test creates profile `alpha`, acquires one lease, opens session A, sets state, reads it back, renews once, and closes. A second session under the same profile reads the persisted cookie/local-storage state while session storage is absent unless the provider explicitly defines context persistence. A competing lease is rejected, an expired lease cannot act, and a separate ephemeral profile cannot observe A's state. A redacted secret is used in one cookie/storage operation and is asserted absent from logs and durable payloads. Repeat the same plan and fixture seed to verify idempotent replay and stable event ordering; use concurrent tasks to verify exclusion rather than timing-based sleeps.

## Safety, limits, and secret constraints

Every operation has one overall deadline, bounded action count, navigation count, event count, response/resource count, payload/storage byte limits, profile disk quota, and aggregate output budget. Limits are resolved before launch and enforced at the provider boundary where possible; materialized data that exceeds a bound is discarded or marked limited, never silently truncated. No unbounded downloads, recursive navigation, arbitrary filesystem paths, unrestricted JavaScript, or uncontrolled parallel browser launches are permitted.

Profile names and paths are opaque Yosoi IDs. Managed paths are allocated under an owned root, canonicalized, and rejected if they escape it. Never log cookie values, authorization headers, storage values, secret references' values, profile paths containing secrets, page text by default, or action arguments marked sensitive. Durable records store hashes, classifications, lengths, and redacted receipts. Import/export and deletion require explicit policy, audit events, and fail-closed behavior; cleanup must run on cancellation, timeout, lease loss, and provider disconnect.

## Lifecycle and concurrency semantics

A profile lease is an exclusive, durable, renewable capability with owner, scope, creation, expiry, fencing generation, and terminal state. Acquisition is atomic; stale generations cannot mutate a profile. Renewal is explicit and bounded, not implicit activity. Lease loss prevents new actions, requests provider cancellation, and yields a typed terminal outcome. Release is idempotent, and recovery reconciles orphaned provider processes and leases without relying on sleep polling.

A session is created only under a valid lease, has an immutable plan, ordered action IDs, and a terminal state. Actions are admitted one at a time per session and are never concurrently interleaved; independent sessions may run concurrently only when profile/provider isolation and configured global limits allow it. Cookie/storage reads and writes have explicit scope (profile, context, origin, or session), operation type, selector, and redacted receipt. Ambiguous ownership, expired/terminal IDs, duplicate mutations, and unknown provider results fail closed. Browser/context/profile cleanup is observable and durable before the operation is finalized.

## Dependencies and implementation order

First finalize the VoidCrawl capability surface and exact revision: managed profile creation/open/close, context isolation, lease-compatible ownership hooks, cookie/storage protocol operations, navigation/input/action primitives, cancellation, and typed receipts. Then implement the Yosoi policy resolver, durable lease/session/action state machines, redaction and audit boundary, adapter conversions, recovery/reconciliation, and conformance fixtures. CAS-333 operating-envelope results and CAS-329–334 evidence/staging contracts are prerequisites. A durable store, monotonic/UTC clock abstraction, secret-provider interface, and test-only deterministic provider are dependencies; no production secret backend or profile persistence should be invented in the fixture.

## Completion evidence

Completion requires committed contract tests and a deterministic fixture proving: fresh isolation; managed-profile persistence boundaries; exclusive acquisition, renewal, fencing, expiry, release, and crash recovery; cookie/local/session-storage read/write/clear semantics; ordered actions and idempotent replay; cancellation and cleanup; all configured limits; concurrent admission without races; redaction (including failure paths); durable audit/provenance and bundle-last finalization; and typed provider/policy failures. Run formatting, warnings-denied Clippy, unit/integration tests, and an exact-revision clean build with local dependency overrides disabled. Record process cleanup, resource usage, and a bounded concurrent soak; absence of leaked profiles, leases, browser processes, or secrets is required evidence.

## Non-goals

This project does not promise arbitrary remote-browser attachment, shared ambient sessions, stealth or challenge bypass, CAPTCHA solving, fingerprint spoofing, unrestricted automation, pixel-identical rendering, cross-browser portability, unbounded profile pools, transactional rollback of websites, or durable capture of raw secrets. It does not replace existing artifact schemas, invent browser identity from page content, or make provider mechanisms into Yosoi policy. Recording/PDF/element-targeted visual features, distributed scheduling, customer-facing compatibility guarantees, and secret-vault implementation remain separate projects unless explicitly added to the resolved scope.
