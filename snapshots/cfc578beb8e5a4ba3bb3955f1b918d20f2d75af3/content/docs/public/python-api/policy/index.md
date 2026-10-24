---
title: "yosoi.policy"
description: "Public declarations in yosoi.policy."
order: 0
---

`yosoi.policy`

Typed policy authoring with Rust-owned defaults and validation.

[Source: python/yosoi/policy.py:1](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L1-L1)

## Types

| Name | Summary |
| --- | --- |
| [`Acquisition`](/yosoi/python-api/policy/types/acquisition/) | Authored acquisition mechanism with explicit document selection. |
| [`AcquisitionKind`](/yosoi/python-api/policy/types/acquisition-kind/) | Resolved acquisition family and optional browser mode. |
| [`BrowserLimits`](/yosoi/python-api/policy/types/browser-limits/) | Browser evidence byte bounds and capture resource counts. |
| [`Continue`](/yosoi/python-api/policy/types/continue/) | Retain an unsuccessful result and attempt the next safe step. |
| [`DocumentSelection`](/yosoi/python-api/policy/types/document-selection/) | Current or explicit document outputs for one acquisition. |
| [`Documents`](/yosoi/python-api/policy/types/documents/) | Retained-payload parsing resource limits. |
| [`Duration`](/yosoi/python-api/policy/types/duration/) | Portable elapsed duration with seconds and subsecond nanoseconds. |
| [`EffectiveAcquisition`](/yosoi/python-api/policy/types/effective-acquisition/) | Resolved acquisition output selection preserving authored intent. |
| [`EffectivePage`](/yosoi/python-api/policy/types/effective-page/) | Resolved acquisitions retained in authored page order. |
| [`EffectivePolicy`](/yosoi/python-api/policy/types/effective-policy/) | Rust-resolved behavior view, separate from caller authoring intent. |
| [`EffectiveProviderRoute`](/yosoi/python-api/policy/types/effective-provider-route/) | Resolved provider profile with its default-selection provenance. |
| [`EffectiveSearch`](/yosoi/python-api/policy/types/effective-search/) | Resolved ordered provider routes and shared search budgets. |
| [`Filters`](/yosoi/python-api/policy/types/filters/) | Explicit Map admission exclusions rather than discovery selectors. |
| [`FlowPolicy`](/yosoi/python-api/policy/types/flow-policy/) | Independent fallback continuation for failures and cancellations. |
| [`Locators`](/yosoi/python-api/policy/types/locators/) | Locator traversal, query, match, and output resource limits. |
| [`Map`](/yosoi/python-api/policy/types/map/) | Complete bounded discovery declaration resolved by the Rust SDK. |
| [`MapLimits`](/yosoi/python-api/policy/types/map-limits/) | Map discovery counts, retention bounds, and execution budgets. |
| [`Page`](/yosoi/python-api/policy/types/page/) | Ordered bounded acquisitions for one page request. |
| [`Policy`](/yosoi/python-api/policy/types/policy/) | Editable complete declaration with Rust-owned defaults and validation. |
| [`PolicyIdentity`](/yosoi/python-api/policy/types/policy-identity/) | Versioned Rust digest identifying effective policy behavior. |
| [`PolicySnapshot`](/yosoi/python-api/policy/types/policy-snapshot/) | Deeply frozen Rust-validated authoring and resolved behavior. |
| [`ProfileSelection`](/yosoi/python-api/policy/types/profile-selection/) | Current provider defaults or an explicit complete request profile. |
| [`Provider`](/yosoi/python-api/policy/types/provider/) | Supported provider names with Rust registry default-status evidence. |
| [`ProviderDefaultsStatus`](/yosoi/python-api/policy/types/provider-defaults-status/) | Explicit registry certification or exact-profile provenance. |
| [`ProviderRequestProfile`](/yosoi/python-api/policy/types/provider-request-profile/) | Complete child-request policy sections for a search provider. |
| [`ProviderSelection`](/yosoi/python-api/policy/types/provider-selection/) | One provider and its current or explicit child-request profile. |
| [`Redirects`](/yosoi/python-api/policy/types/redirects/) | Direct HTTP redirect traversal configuration. |
| [`Request`](/yosoi/python-api/policy/types/request/) | Acquisition deadlines and source/browser evidence budgets. |
| [`Scope`](/yosoi/python-api/policy/types/scope/) | Map URL admission boundaries relative to the authored seed. |
| [`Search`](/yosoi/python-api/policy/types/search/) | Ordered provider selection with shared search resource budgets. |
| [`SourceLimits`](/yosoi/python-api/policy/types/source-limits/) | Separate retained byte budgets for the HTTP source stages. |
| [`Stop`](/yosoi/python-api/policy/types/stop/) | Stop a selected Flow scope after failure or cancellation. |
| [`Tuning`](/yosoi/python-api/policy/types/tuning/) | Package-owned tuning mode without independent runtime overrides. |

## Aliases

| Name | Summary |
| --- | --- |
| [`AccessibilityNodeLimitValue`](/yosoi/python-api/policy/aliases/accessibility-node-limit-value/) | Strict positive addressable u32 accessibility-node bound validated by Rust. |
| [`AddressableByteLimitValue`](/yosoi/python-api/policy/aliases/addressable-byte-limit-value/) | Strict positive u64 byte limit checked by Rust to fit platform address size. |
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
| [`MaximumElapsedValue`](/yosoi/python-api/policy/aliases/maximum-elapsed-value/) | Strict positive u64 elapsed budget in microseconds. Conversion to a platform capture deadline is checked separately. |
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

## Constants

| Name | Summary |
| --- | --- |
| [`U16`](/yosoi/python-api/policy/constants/u16/) | Strict integer from zero through the u16 maximum. Numeric strings, booleans, and floats are not coerced. |
| [`U64`](/yosoi/python-api/policy/constants/u64/) | Strict integer from zero through the u64 maximum; units depend on the consuming field. |
