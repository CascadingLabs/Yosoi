---
title: "Python reference"
description: "Public Python modules, types, functions, and source declarations."
order: 0
---

Use `import yosoi as ys`. Browse modules, then Types, Functions, Aliases, or Constants. Each symbol has its own page.

This reference is generated from public Python source declarations without importing or executing the native extension. Signatures preserve Python annotations, defaults, and async declarations. Class pages show declared fields and methods; inherited or dynamically generated members are not expanded.

## Package exports

| Name | Summary |
| --- | --- |
| [`ys.Archive`](/yosoi/python-api/archive/types/archive/) | Local Unix Archive handle with no open files between operations. |
| [`ys.AutomationRecord`](/yosoi/python-api/archive/types/automation-record/) | Bounded observations and receipts validated by the Rust record contract. |
| [`ys.BoundFlow`](/yosoi/python-api/browser/types/bound-flow/) | Retain an immutable Flow with a validated policy snapshot. |
| [`ys.BrowserCleanupError`](/yosoi/python-api/browser/types/browser-cleanup-error/) | Retain cleanup failures alongside the original operation exception. |
| [`ys.BrowserError`](/yosoi/python-api/browser/aliases/browser-error/) | Native browser acquisition, execution, policy, or cleanup exception. |
| [`ys.CancellationToken`](/yosoi/python-api/cancellation/types/cancellation-token/) | Share a caller-controlled cancellation signal with SDK operations. |
| [`ys.Continuation`](/yosoi/python-api/policy/aliases/continuation/) | Tagged Continue or Stop behavior for known failures and observed cancellations. Retaining a result does not imply successful business effects. |
| [`ys.Continue`](/yosoi/python-api/policy/types/continue/) | Retain an unsuccessful result and attempt the next safe step. |
| [`ys.Contract`](/yosoi/python-api/contracts/types/contract/) | Mutable Pydantic record model with native candidate extraction. |
| [`ys.Document`](/yosoi/python-api/documents/types/document/) | Immutable document bytes with retained native parse ownership. |
| [`ys.ExtractionPolicy`](/yosoi/python-api/contracts/types/extraction-policy/) | Immutable acceptance and native-work limits for Python Contract extraction. |
| [`ys.Field`](/yosoi/python-api/contracts/functions/field/) | Describe a Contract field using a genuine Pydantic FieldInfo. |
| [`ys.Flow`](/yosoi/python-api/browser/types/flow/) | Declare ordered browser steps without acquiring a Session. |
| [`ys.FlowExecutionError`](/yosoi/python-api/browser/types/flow-execution-error/) | Raise strict completion failure while preserving the Flow outcome. |
| [`ys.FlowInvocationError`](/yosoi/python-api/browser/types/flow-invocation-error/) | Retain native invocation failure and any partial execution evidence. |
| [`ys.FlowOutcome`](/yosoi/python-api/browser/types/flow-outcome/) | Retain executed, skipped, and cleanup facts for a Flow invocation. |
| [`ys.FlowPolicy`](/yosoi/python-api/policy/types/flow-policy/) | Independent fallback continuation for failures and cancellations. |
| [`ys.Money`](/yosoi/python-api/contracts/types/money/) | USD monetary scalar represented by integer minor units. |
| [`ys.Plan`](/yosoi/python-api/locators/types/plan/) | Compiled immutable outputs and repeated-region declarations. |
| [`ys.Policy`](/yosoi/python-api/policy/types/policy/) | Editable complete declaration with Rust-owned defaults and validation. |
| [`ys.Session`](/yosoi/python-api/browser/types/session/) | An acquired Rust Session, released by async context exit. |
| [`ys.SessionPolicy`](/yosoi/python-api/browser/types/session-policy/) | Configure Rust-owned limits and capabilities for a retained Session. |
| [`ys.Stop`](/yosoi/python-api/policy/types/stop/) | Stop a selected Flow scope after failure or cancellation. |
| [`ys.StopScope`](/yosoi/python-api/policy/aliases/stop-scope/) | current_flow stops its remaining leaves; invocation stops all remaining invocation work. Unknown effects can still force a hard safety stop. |
| [`ys.View`](/yosoi/python-api/view/types/view/) | One bounded page of captured DOM evidence, independent of a live browser. |
| [`ys.Work`](/yosoi/python-api/browser/types/work/) | An explicit browser control lease owned by one Session. |
| `ys.__version__` | Installed distribution version |
| [`ys.accessibility_state`](/yosoi/python-api/locators/functions/accessibility-state/) | Declare a boolean accessibility-state query without browser I/O. |
| [`ys.accessibility_text`](/yosoi/python-api/locators/functions/accessibility-text/) | Author accessibility node text query intent without document I/O. |
| [`ys.accessible_name`](/yosoi/python-api/locators/functions/accessible-name/) | Author accessible node name query intent without document I/O. |
| [`ys.all_of`](/yosoi/python-api/browser/functions/all-of/) | Combine expectations so every child must be satisfied. |
| [`ys.archive`](/yosoi/python-api/archive/) | Module |
| [`ys.assert_all`](/yosoi/python-api/browser/functions/assert-all/) | Check one typed Contract observation using synchronous local predicates. |
| [`ys.assert_that`](/yosoi/python-api/browser/functions/assert-that/) | Declare an immediate check of a DOM condition. |
| [`ys.ax`](/yosoi/python-api/browser/functions/ax/) | Declare an accessibility expectation for Until. |
| [`ys.browser`](/yosoi/python-api/browser/) | Module |
| [`ys.check`](/yosoi/python-api/browser/functions/check/) | Author one named synchronous Contract predicate. |
| [`ys.click`](/yosoi/python-api/browser/functions/click/) | Declare one click without dispatching it. |
| [`ys.contracts`](/yosoi/python-api/contracts/) | Module |
| [`ys.count_at_least`](/yosoi/python-api/browser/functions/count-at-least/) | Declare a minimum DOM match count for Until. |
| [`ys.css`](/yosoi/python-api/locators/functions/css/) | Author CSS tree-node query intent without document I/O. |
| [`ys.documents`](/yosoi/python-api/documents/) | Module |
| [`ys.enter_text`](/yosoi/python-api/browser/functions/enter-text/) | Declare a text input action without executing it. |
| [`ys.evaluate`](/yosoi/python-api/browser/functions/evaluate/) | Declare JavaScript evaluation without executing the source. |
| [`ys.evaluate_file`](/yosoi/python-api/browser/functions/evaluate-file/) | Take a bounded, Rust-validated snapshot of one UTF-8 JavaScript file. |
| [`ys.exists`](/yosoi/python-api/browser/functions/exists/) | Declare an element-existence expectation for Until. |
| [`ys.extract`](/yosoi/python-api/contracts/functions/extract/) | Return validated Pydantic models extracted from a document. |
| [`ys.extract_report`](/yosoi/python-api/contracts/functions/extract-report/) | Return a report with accepted models, rejected candidates, and evidence. |
| [`ys.flow`](/yosoi/python-api/browser/functions/flow/) | Build an immutable Flow, retaining Rust defaults unless configured. |
| [`ys.json_path`](/yosoi/python-api/locators/functions/json-path/) | Author supported Rust JSONPath value query intent without document I/O. |
| [`ys.json_pointer`](/yosoi/python-api/locators/functions/json-pointer/) | Author JSON Pointer value query intent without document I/O. |
| [`ys.locators`](/yosoi/python-api/locators/) | Module |
| [`ys.map`](/yosoi/python-api/map/) | Module |
| [`ys.navigate`](/yosoi/python-api/browser/functions/navigate/) | Declare navigation without acquiring or changing a browser. |
| [`ys.output`](/yosoi/python-api/locators/functions/output/) | Name one explicit query and projection declaration. |
| [`ys.policy`](/yosoi/python-api/policy/) | Module |
| [`ys.regex`](/yosoi/python-api/locators/functions/regex/) | Author decoded-text regular-expression range query intent without document I/O. |
| [`ys.request`](/yosoi/python-api/request/) | Module |
| [`ys.response`](/yosoi/python-api/browser/functions/response/) | Declare a matching network-response expectation for Until. |
| [`ys.role`](/yosoi/python-api/locators/functions/role/) | Author accessibility role query intent without document I/O. |
| [`ys.run_module`](/yosoi/python-api/browser/functions/run-module/) | Snapshot a bounded relative JavaScript module graph from disk. |
| [`ys.run_module_with_export`](/yosoi/python-api/browser/functions/run-module-with-export/) | Snapshot a JavaScript module graph and read one named export as JSON. |
| [`ys.screenshot`](/yosoi/python-api/browser/functions/screenshot/) | Declare screenshot capture without executing it. |
| [`ys.search`](/yosoi/python-api/search/) | Module |
| [`ys.session`](/yosoi/python-api/browser/functions/session/) | Create an async context manager for an explicitly owned browser Session. |
| [`ys.text_literal`](/yosoi/python-api/locators/functions/text-literal/) | Author decoded-text literal range query intent without document I/O. |
| [`ys.timed`](/yosoi/python-api/browser/functions/timed/) | Apply a positive, explicit millisecond timeout to one action. |
| [`ys.tree_text_contains`](/yosoi/python-api/locators/functions/tree-text-contains/) | Author tree descendant-text substring query intent without document I/O. |
| [`ys.until`](/yosoi/python-api/browser/functions/until/) | Declare an expectation wait around an optional one-shot trigger. |
| [`ys.view`](/yosoi/python-api/view/) | Module |
| [`ys.visible`](/yosoi/python-api/browser/functions/visible/) | Declare a browser visibility expectation for Until. |
| [`ys.wait`](/yosoi/python-api/browser/functions/wait/) | Declare an explicit duration rather than a readiness condition. |
| [`ys.wait_until`](/yosoi/python-api/browser/functions/wait-until/) | Declare a bounded DOM-condition wait. |
| [`ys.xpath`](/yosoi/python-api/locators/functions/xpath/) | Author XPath tree-node query intent without document I/O. |

## Modules

- [`yosoi.archive`](/yosoi/python-api/archive/)
- [`yosoi.browser`](/yosoi/python-api/browser/)
- [`yosoi.cancellation`](/yosoi/python-api/cancellation/)
- [`yosoi.contracts`](/yosoi/python-api/contracts/)
- [`yosoi.diagnostics`](/yosoi/python-api/diagnostics/)
- [`yosoi.documents`](/yosoi/python-api/documents/)
- [`yosoi.errors`](/yosoi/python-api/errors/)
- [`yosoi.identities`](/yosoi/python-api/identities/)
- [`yosoi.locators`](/yosoi/python-api/locators/)
- [`yosoi.map`](/yosoi/python-api/map/)
- [`yosoi.outcomes`](/yosoi/python-api/outcomes/)
- [`yosoi.policy`](/yosoi/python-api/policy/)
- [`yosoi.request`](/yosoi/python-api/request/)
- [`yosoi.runtime_contracts`](/yosoi/python-api/runtime-contracts/)
- [`yosoi.scalars`](/yosoi/python-api/scalars/)
- [`yosoi.search`](/yosoi/python-api/search/)
- [`yosoi.view`](/yosoi/python-api/view/)

[Source: python/yosoi/__init__.py:1](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/__init__.py#L1-L1)
