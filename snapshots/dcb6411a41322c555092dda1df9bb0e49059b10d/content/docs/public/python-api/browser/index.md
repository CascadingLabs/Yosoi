---
title: "yosoi.browser"
description: "Public declarations in yosoi.browser."
order: 0
---

`yosoi.browser`

Typed flows and async access to the Rust browser Session and Action APIs.

[Source: python/yosoi/browser.py:1](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L1-L1)

## Types

| Name | Summary |
| --- | --- |
| [`AccessibilityExpectation`](/yosoi/python-api/browser/types/accessibility-expectation/) | Observe an accessible name and optional role during Until. |
| [`AllExpectation`](/yosoi/python-api/browser/types/all-expectation/) | Require every child expectation within one Until wait. |
| [`Assert`](/yosoi/python-api/browser/types/assert/) | Declare an immediate DOM condition check. |
| [`BoundFlow`](/yosoi/python-api/browser/types/bound-flow/) | Retain an immutable Flow with a validated policy snapshot. |
| [`BrowserCleanupError`](/yosoi/python-api/browser/types/browser-cleanup-error/) | Retain cleanup failures alongside the original operation exception. |
| [`BrowserExecutionIdentity`](/yosoi/python-api/browser/types/browser-execution-identity/) | Keep controller, engine claims and owned executable facts distinct. |
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

## Functions

| Name | Summary |
| --- | --- |
| [`action`](/yosoi/python-api/browser/functions/action/) | Navigate to ``url``, then run the flow with managed SDK cleanup. |
| [`all_of`](/yosoi/python-api/browser/functions/all-of/) | Combine expectations so every child must be satisfied. |
| [`assert_all`](/yosoi/python-api/browser/functions/assert-all/) | Check one typed Contract observation using synchronous local predicates. |
| [`assert_that`](/yosoi/python-api/browser/functions/assert-that/) | Declare an immediate check of a DOM condition. |
| [`ax`](/yosoi/python-api/browser/functions/ax/) | Declare an accessibility expectation for Until. |
| [`check`](/yosoi/python-api/browser/functions/check/) | Author one named synchronous Contract predicate. |
| [`click`](/yosoi/python-api/browser/functions/click/) | Declare one click without dispatching it. |
| [`count_at_least`](/yosoi/python-api/browser/functions/count-at-least/) | Declare a minimum DOM match count for Until. |
| [`enter_text`](/yosoi/python-api/browser/functions/enter-text/) | Declare a text input action without executing it. |
| [`evaluate`](/yosoi/python-api/browser/functions/evaluate/) | Declare JavaScript evaluation without executing the source. |
| [`evaluate_file`](/yosoi/python-api/browser/functions/evaluate-file/) | Take a bounded, Rust-validated snapshot of one UTF-8 JavaScript file. |
| [`exists`](/yosoi/python-api/browser/functions/exists/) | Declare an element-existence expectation for Until. |
| [`flow`](/yosoi/python-api/browser/functions/flow/) | Build an immutable Flow, retaining Rust defaults unless configured. |
| [`navigate`](/yosoi/python-api/browser/functions/navigate/) | Declare navigation without acquiring or changing a browser. |
| [`response`](/yosoi/python-api/browser/functions/response/) | Declare a matching network-response expectation for Until. |
| [`run_module`](/yosoi/python-api/browser/functions/run-module/) | Snapshot a bounded relative JavaScript module graph from disk. |
| [`run_module_with_export`](/yosoi/python-api/browser/functions/run-module-with-export/) | Snapshot a JavaScript module graph and read one named export as JSON. |
| [`screenshot`](/yosoi/python-api/browser/functions/screenshot/) | Declare screenshot capture without executing it. |
| [`session`](/yosoi/python-api/browser/functions/session/) | Create an async context manager for an explicitly owned browser Session. |
| [`timed`](/yosoi/python-api/browser/functions/timed/) | Apply a positive, explicit millisecond timeout to one action. |
| [`until`](/yosoi/python-api/browser/functions/until/) | Declare an expectation wait around an optional one-shot trigger. |
| [`visible`](/yosoi/python-api/browser/functions/visible/) | Declare a browser visibility expectation for Until. |
| [`wait`](/yosoi/python-api/browser/functions/wait/) | Declare an explicit duration rather than a readiness condition. |
| [`wait_until`](/yosoi/python-api/browser/functions/wait-until/) | Declare a bounded DOM-condition wait. |

## Aliases

| Name | Summary |
| --- | --- |
| [`ActionKind`](/yosoi/python-api/browser/aliases/action-kind/) | Session policy action names used to allow or reject browser operations. |
| [`BrowserError`](/yosoi/python-api/browser/aliases/browser-error/) | Native browser acquisition, execution, policy, or cleanup exception. |
| [`BrowserMode`](/yosoi/python-api/browser/aliases/browser-mode/) | Native browser display mode: headless or headful. |
| [`Condition`](/yosoi/python-api/browser/aliases/condition/) | DOM condition tagged as existence, visibility, or minimum match count. |
| [`ExecutionConcurrency`](/yosoi/python-api/browser/aliases/execution-concurrency/) | Strict admitted execution capacity from one through 32 permits. |
| [`FlowTermination`](/yosoi/python-api/browser/aliases/flow-termination/) | Flow terminal states retaining issues, uncertainty, and cancellation. |
| [`HttpStatus`](/yosoi/python-api/browser/aliases/http-status/) | Strict integer HTTP status from 100 through 599; booleans are rejected. |
| [`MaximumQueuedOperations`](/yosoi/python-api/browser/aliases/maximum-queued-operations/) | Strict queue capacity from one through 1,024 waiting operations. |
| [`OperationStatus`](/yosoi/python-api/browser/aliases/operation-status/) | Observed, rejected, or unknown operation state; unknown preserves uncertainty. |
| [`PositiveMilliseconds`](/yosoi/python-api/browser/aliases/positive-milliseconds/) | Positive integer milliseconds whose microsecond conversion fits in u64. |
| [`PositiveU32`](/yosoi/python-api/browser/aliases/positiveu32/) | Strict integer from 1 through 2**32 - 1 for positive browser values. |
| [`PositiveU64`](/yosoi/python-api/browser/aliases/positiveu64/) | Strict integer from 1 through 2**64 - 1 for positive browser values. |
| [`Step`](/yosoi/python-api/browser/aliases/step/) | Tagged browser action, wrapper, nested Flow, or Until declaration. |
| [`StopCause`](/yosoi/python-api/browser/aliases/stop-cause/) | Explicit failure, cancellation, unknown-outcome, or unsafe-state stop cause. |
| [`UntilCheckSource`](/yosoi/python-api/browser/aliases/until-check-source/) | Evidence source used by a DOM, accessibility, or network expectation check. |
| [`UntilCheckState`](/yosoi/python-api/browser/aliases/until-check-state/) | Per-check pending, satisfied, rejected, or unavailable evaluation state. |
| [`UntilExpectation`](/yosoi/python-api/browser/aliases/until-expectation/) | Tagged DOM, Contract, accessibility, network, or combined Until expectation. |
| [`UntilTermination`](/yosoi/python-api/browser/aliases/until-termination/) | Wait terminal states preserving unsuccessful and uncertain observations. |

## Constants

| Name | Summary |
| --- | --- |
| [`MAX_UNTIL_REPORT_BYTES`](/yosoi/python-api/browser/constants/max-until-report-bytes/) | Maximum encoded Until report size in bytes, currently 1 MiB. |
| [`U64`](/yosoi/python-api/browser/constants/u64/) | Strict integer from 0 through 2**64 - 1 for unsigned browser values. |
