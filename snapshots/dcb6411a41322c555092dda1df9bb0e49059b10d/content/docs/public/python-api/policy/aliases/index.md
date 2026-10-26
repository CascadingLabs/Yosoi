---
title: "Aliases"
description: "Aliases declared in yosoi.policy."
order: 0
---

| Name | Summary |
| --- | --- |
| [`AccessibilityNodeLimitValue`](/yosoi/python-api/policy/aliases/accessibility-node-limit-value/) | Strict positive addressable u32 accessibility-node bound validated by Rust. |
| [`AddressableByteLimitValue`](/yosoi/python-api/policy/aliases/addressable-byte-limit-value/) | Strict positive u64 byte limit checked by Rust to fit platform address size. |
| [`BrowserEngine`](/yosoi/python-api/policy/aliases/browser-engine/) | Browser implementation. Optional engines use native BiDi; Chrome retains CDP. |
| [`BrowserMode`](/yosoi/python-api/policy/aliases/browser-mode/) | Headless or headful acquisition mode. Session settings and bound browser acquisitions must agree before startup. |
| [`BudgetValue`](/yosoi/python-api/policy/aliases/budget-value/) | Strict positive u32 Map budget validated by Rust; zero is not an unlimited setting. |
| [`Continuation`](/yosoi/python-api/policy/aliases/continuation/) | Tagged Continue or Stop behavior for known failures and observed cancellations. Retaining a result does not imply successful business effects. |
| [`CountLimitValue`](/yosoi/python-api/policy/aliases/count-limit-value/) | Strict positive u64 policy count validated by Rust; zero never means unlimited. |
| [`DirectHttpRedirectTargets`](/yosoi/python-api/policy/aliases/direct-http-redirect-targets/) | Redirect admission allows supported HTTP(S) destinations or restricts transitions to the seed origin. Hop and request budgets apply separately. |
| [`DiscoveryDocuments`](/yosoi/python-api/policy/aliases/discovery-documents/) | Map evidence retention either discards documents after inspection or retains them within the configured payload budget. |
| [`DocumentRequest`](/yosoi/python-api/policy/aliases/document-request/) | Requested output evidence families. Selection does not guarantee production; inspect typed partial, unavailable, or unprojectable outcomes. |
| [`DocumentSelectionKind`](/yosoi/python-api/policy/aliases/document-selection-kind/) | Current selection resolves package output defaults; exact selection preserves authored outputs, including an intentionally empty selection. |
| [`EventLimitValue`](/yosoi/python-api/policy/aliases/event-limit-value/) | Strict positive addressable browser event count validated by Rust. |
| [`HostScope`](/yosoi/python-api/policy/aliases/host-scope/) | Map admission stays on the seed host or the supported registrable domain. Passive discoveries do not prove HTTP reachability. |
| [`IpFamily`](/yosoi/python-api/policy/aliases/ip-family/) | Permitted outbound TCP family; an upstream proxy owns its destination family. |
| [`MaximumElapsedValue`](/yosoi/python-api/policy/aliases/maximum-elapsed-value/) | Strict positive u64 elapsed budget in microseconds. Conversion to a platform capture deadline is checked separately. |
| [`MoliProfile`](/yosoi/python-api/policy/aliases/moli-profile/) | Moli DOM-only or on-demand layout profile, independent of window mode. |
| [`PageDiscovery`](/yosoi/python-api/policy/aliases/page-discovery/) | Disable ordinary page-link exploration or explore admitted pages within depth and resource budgets. |
| [`PathScope`](/yosoi/python-api/policy/aliases/path-scope/) | Map admission stays within the seed path subtree or admits the entire origin; scheme, port, and host rules remain independent. |
| [`PositiveInt`](/yosoi/python-api/policy/aliases/positive-int/) | Strict positive Python integer. Native policy validation applies operation-specific width and plan constraints. |
| [`PositiveU16`](/yosoi/python-api/policy/aliases/positiveu16/) | Strict positive u16 integer; zero and numeric coercions are rejected. |
| [`PositiveU32`](/yosoi/python-api/policy/aliases/positiveu32/) | Strict positive u32 integer; zero and numeric coercions are rejected. |
| [`PositiveU64`](/yosoi/python-api/policy/aliases/positiveu64/) | Strict positive u64 integer; zero and numeric coercions are rejected. |
| [`ProfileSelectionKind`](/yosoi/python-api/policy/aliases/profile-selection-kind/) | Current provider profiles resolve registry metadata; exact profiles retain complete authored child-request sections. |
| [`RedirectHopLimitValue`](/yosoi/python-api/policy/aliases/redirect-hop-limit-value/) | Strict positive u32 Direct HTTP redirect-transition bound validated by Rust. |
| [`ResourceLimitValue`](/yosoi/python-api/policy/aliases/resource-limit-value/) | Strict positive addressable u32 resource-count bound validated by Rust. |
| [`Robots`](/yosoi/python-api/policy/aliases/robots/) | Ignore or respect applicable robots rules during Map exploration. This does not change URL scope admission. |
| [`StepLimitValue`](/yosoi/python-api/policy/aliases/step-limit-value/) | Strict positive u32 query/depth counter validated by Rust. |
| [`StopScope`](/yosoi/python-api/policy/aliases/stop-scope/) | current_flow stops its remaining leaves; invocation stops all remaining invocation work. Unknown effects can still force a hard safety stop. |
| [`Subdomains`](/yosoi/python-api/policy/aliases/subdomains/) | Disable name discovery or use passive historical provider evidence, without guessing hosts or claiming current reachability. |
| [`TuningMode`](/yosoi/python-api/policy/aliases/tuning-mode/) | Current supported tuning vocabulary uses package defaults; no separate override mode is implied. |
