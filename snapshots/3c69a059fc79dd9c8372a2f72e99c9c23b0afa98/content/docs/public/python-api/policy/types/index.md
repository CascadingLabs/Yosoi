---
title: "Types"
description: "Types declared in yosoi.policy."
order: 0
---

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
