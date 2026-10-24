---
title: "Types"
description: "Types declared in yosoi.browser."
order: 0
---

| Name | Summary |
| --- | --- |
| [`AccessibilityExpectation`](/yosoi/python-api/browser/types/accessibility-expectation/) | Observe an accessible name and optional role during Until. |
| [`AllExpectation`](/yosoi/python-api/browser/types/all-expectation/) | Require every child expectation within one Until wait. |
| [`Assert`](/yosoi/python-api/browser/types/assert/) | Declare an immediate DOM condition check. |
| [`BoundFlow`](/yosoi/python-api/browser/types/bound-flow/) | Retain an immutable Flow with a validated policy snapshot. |
| [`BrowserCleanupError`](/yosoi/python-api/browser/types/browser-cleanup-error/) | Retain cleanup failures alongside the original operation exception. |
| [`Check`](/yosoi/python-api/browser/types/check/) | Name a synchronous local predicate for Contract assertions. |
| [`Click`](/yosoi/python-api/browser/types/click/) | Declare a single click on the current browser page. |
| [`ConditionExpectation`](/yosoi/python-api/browser/types/condition-expectation/) | Observe a DOM condition as part of an Until wait. |
| [`Configured`](/yosoi/python-api/browser/types/configured/) | Override continuation decisions for one action. |
| [`CountAtLeast`](/yosoi/python-api/browser/types/count-at-least/) | Declare a minimum number of matching DOM elements. |
| [`Duration`](/yosoi/python-api/browser/types/duration/) | Represent a persisted Rust duration with explicit units. |
| [`EnterText`](/yosoi/python-api/browser/types/enter-text/) | Declare text input on the current browser page. |
| [`Evaluate`](/yosoi/python-api/browser/types/evaluate/) | Declare JavaScript evaluation in the browser page. |
| [`EvaluateFile`](/yosoi/python-api/browser/types/evaluate-file/) | Retain a construction-time JavaScript file snapshot. |
| [`EvaluateModule`](/yosoi/python-api/browser/types/evaluate-module/) | Retain a construction-time local JavaScript module graph. |
| [`Exists`](/yosoi/python-api/browser/types/exists/) | Declare that at least one matching DOM element must exist. |
| [`Flow`](/yosoi/python-api/browser/types/flow/) | Declare ordered browser steps without acquiring a Session. |
| [`FlowExecutionError`](/yosoi/python-api/browser/types/flow-execution-error/) | Raise strict completion failure while preserving the Flow outcome. |
| [`FlowInvocationError`](/yosoi/python-api/browser/types/flow-invocation-error/) | Retain native invocation failure and any partial execution evidence. |
| [`FlowOutcome`](/yosoi/python-api/browser/types/flow-outcome/) | Retain executed, skipped, and cleanup facts for a Flow invocation. |
| [`FlowStopReason`](/yosoi/python-api/browser/types/flow-stop-reason/) | Explain where execution stopped and which continuation applied. |
| [`JsonMatch`](/yosoi/python-api/browser/types/json-match/) | Compare a response JSON value at an RFC 6901 pointer. |
| [`LocalContractExpectation`](/yosoi/python-api/browser/types/local-contract-expectation/) | Retain an inspectable descriptor for local Contract checks. |
| [`LocalRustAssertion`](/yosoi/python-api/browser/types/local-rust-assertion/) | Retain a local Contract assertion descriptor for inspection. |
| [`Navigate`](/yosoi/python-api/browser/types/navigate/) | Declare navigation to a URL on the leased browser tab. |
| [`NestedFlow`](/yosoi/python-api/browser/types/nested-flow/) | Execute a nested Flow within its enclosing invocation. |
| [`Observation`](/yosoi/python-api/browser/types/observation/) | Retain browser evidence from a particular document epoch. |
| [`OperationReceipt`](/yosoi/python-api/browser/types/operation-receipt/) | Retain observed, rejected, or unknown facts about an operation. |
| [`ResponseExpectation`](/yosoi/python-api/browser/types/response-expectation/) | Observe a matching network response during an Until wait. |
| [`Screenshot`](/yosoi/python-api/browser/types/screenshot/) | Declare screenshot capture from the current browser tab. |
| [`Session`](/yosoi/python-api/browser/types/session/) | An acquired Rust Session, released by async context exit. |
| [`SessionPolicy`](/yosoi/python-api/browser/types/session-policy/) | Configure Rust-owned limits and capabilities for a retained Session. |
| [`SkippedStep`](/yosoi/python-api/browser/types/skipped-step/) | Retain a declared step that was not started after a stop decision. |
| [`StepOutcome`](/yosoi/python-api/browser/types/step-outcome/) | Retain one executed step with failure and cancellation facts. |
| [`Timed`](/yosoi/python-api/browser/types/timed/) | Apply a local execution deadline to one action. |
| [`TriggerStep`](/yosoi/python-api/browser/types/trigger-step/) | A one-shot action that can be followed by a bounded expectation wait. |
| [`UntilCheck`](/yosoi/python-api/browser/types/until-check/) | Retain the state and evidence of one expectation check. |
| [`UntilReport`](/yosoi/python-api/browser/types/until-report/) | Retain a typed Until result within the authoritative Flow outcome. |
| [`UntilScope`](/yosoi/python-api/browser/types/until-scope/) | Fence an Until report to its Session, tab, and document. |
| [`UntilStep`](/yosoi/python-api/browser/types/until-step/) | Observe an expectation around an optional one-shot trigger. |
| [`Visible`](/yosoi/python-api/browser/types/visible/) | Declare that a matching element must satisfy browser visibility checks. |
| [`Wait`](/yosoi/python-api/browser/types/wait/) | Declare an explicit elapsed-time wait. |
| [`WaitExpectation`](/yosoi/python-api/browser/types/wait-expectation/) | An expectation that can wait on the current page without a trigger. |
| [`WaitUntil`](/yosoi/python-api/browser/types/wait-until/) | Declare a bounded wait for a DOM condition. |
| [`Work`](/yosoi/python-api/browser/types/work/) | An explicit browser control lease owned by one Session. |
