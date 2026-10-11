# Rust first-pass requirement audit

Scope authority: Andrew approved implementation, then explicitly excluded Python
and directed runtime validation into the existing Yosoi Docker containers.
CAS-562–567 remain later-pass work. Remote attachment, isolated JS worlds,
continuous network/AX collection, browser-memory restoration and production
release certification are disclosed limits, not implemented capabilities.

Evidence is local and scoped. `docker-core-final-validation-v2.log` records the
integrated browser/Archive/View path; `docker-core-safety-final-validation.log`
records final safety controls. `approved-model-validation.log` records 14 model,
Archive, View and existing public-SDK checks. `final-http-only-check.log` records
the browser-feature-free build. Terminal results, rather than this table alone,
are authoritative.

| Issue | Requirement and authoritative evidence |
| --- | --- |
| CAS-537 | `session.rs` defaults/validation/builder precedence; HTTP remains default. README separates managed and explicit control. Default-denied JS and DOM-disabled observations are exercised in safety checks. |
| CAS-538 | Engine Session owns existing runtime leases/manager; actual Requests reuse them. Close/cancel and two-process reservation controls are exercised. Remote borrowing remains Unsupported. |
| CAS-539 | Shared concrete-tab gate, 32 waiting acquisitions, held-Work command admission, revocation and dispatch fences; competing-owner, queue saturation, independent-tab and drop/deadline controls are exercised. |
| CAS-540 | Read-only Watch API, bounded Arc receipt fanout, pre-subscription, no worker auto-subscription; two-watch/cross-tab, lag, subscriber close and Session cancellation controls are exercised. |
| CAS-541 | Browser Request uses engine Session and existing capture/execution code; default HTTP authoring is unchanged. Two held-Work Requests, immutable Documents after close, cleanup, deadline and dropped-future controls are exercised. |
| CAS-542 | Existing single-connection flattened target routing; two-tab/frame operations and correlated Watch receipts, tab-close isolation. Remote/container endpoint attachment is explicitly Unsupported; owned local execution inside Docker is verified. |
| CAS-543 | Shared loopback fixture runs real browser Requests, Work, two Watchers and lifecycle cleanup. The Docker run uses current test binaries, not baked benchmark binaries. |
| CAS-544 | Serializable typed Flow/Step/Condition/Outcome models; bounded input, sequential stop semantics, explicit wait versus condition wait, no panic assertions; model and browser proof. |
| CAS-545 | Shared native navigate/click/text/screenshot primitives, current selector uniqueness and authority checks, linked capture/operation IDs and honest Unknown outcomes; live controlled proof. |
| CAS-546 | Managed and borrowed paths use the same scoped-policy executor; borrowed Work is not reacquired or closed. Primary outcome is retained with cleanup errors; failure stops and cancellation fences possible dispatch. |
| CAS-547 | Typed expected/actual assertion results, observer-driven deadline waits and opt-in separate failure screenshot receipt. Drift capture preserves the failed terminal and survives replay. |
| CAS-548 | Runnable simple/explicit examples, passing and failing Flows, screenshot artifacts, current syntax in README versus preserved design sketches. Python is out of scope by Andrew's later instruction. |
| CAS-549 | JS permission is separate and defaults off; bounded source/results, frame/world selection contract, shared IDs and cancellation-not-rollback semantics. Retained versus transient limits are disclosed. |
| CAS-550 | Existing provider evaluation on held Work, unique frame/epoch guards, JSON/non-JSON/exception/oversized-result outcomes, unknown mutation and timeout fences. Isolated world is typed Unsupported. |
| CAS-551 | Actual value 42, mutation and exception receipts, default denial and timeout/result controls; JS archive branch records the actual JS-enabled policy. |
| CAS-552 | Versioned AutomationRecord/Context vocabulary, effective Policy identity, Session settings, provider/browser/source metadata, lineage and advisory fingerprints. No raw provider handle is persisted. |
| CAS-553 | Real Archive Documents with integrity references, fresh-process read, missing record/payload and same-length tamper rejection; captures survive Session close. |
| CAS-554 | Chrome-disabled fresh-process replay reconstructs retained evidence and verifies supported Exists/count assertions. Wrong capture/cursor and unsupported Visible are typed; no live effect dispatch. |
| CAS-555 | Explicit new Session rerun has fresh IDs and linked record. Changed fixture produces count 4 versus expected 12, a rejected assertion and failure screenshot. No arbitrary-site determinism claim. |
| CAS-556 | Capture identity includes observation/session/tab/epoch; cursors cannot mix captures, raw evidence remains accessible, missing/stale/foreign references are typed. |
| CAS-557 | Bounded deterministic DOM rows, exact source inspect references, capture-bound pagination and visible unavailable-modality outcomes; Actions do not require paginating the View. |
| CAS-558 | Same projection constructor for live and archived observations; old View retains its capture, a fresh capture rejects its cursor and live selectors are resolved again. No AI discovery/ranking. |
| CAS-559 | One shared fixture, supported/unsupported matrix, positive/negative controls, Docker image/binary/source identity, and one owner expensive-command grant. Python validation is explicitly removed from this gate. |
| CAS-560 | Integrated controlled Docker evidence spans all six projects; independent source review found and corrected Request drop/deadline/empty-selection outcome gaps. Host experiments are historical, not current proof. |
| CAS-561 | README, this audit, runnable container adapter, ignored evidence/Archive artifacts and local JJ bookmark provide the review handoff. Next-pass corrections are explicit; no production continuation, push or release is implied. |

Source/source-revision strings in records are harness metadata. The image's
existing entrypoint independently verifies regular Chrome product/version/digest.
This audit does not certify full CI, all platforms, all sites, headful operation,
performance, distributed placement or a production 0.2.0 release.
