---
title: "yosoi.map"
description: "Public declarations in yosoi.map."
order: 0
---

`yosoi.map`

Bounded discovery uses the Rust SDK's frontier, budgets and outcomes.

[Source: python/yosoi/map.py:1](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/map.py#L1-L1)

## Types

| Name | Summary |
| --- | --- |
| [`BoundMapRequest`](/yosoi/python-api/map/types/bound-map-request/) | A discovery request bound to a serialized policy snapshot. |
| [`DiscoverySource`](/yosoi/python-api/map/types/discovery-source/) | Provenance category for a retained hostname or page. |
| [`Exploration`](/yosoi/python-api/map/types/exploration/) | Retained page exploration state, independent of discovery provenance. |
| [`FrontierEntry`](/yosoi/python-api/map/types/frontier-entry/) | Unfinished page work, without a promise of later execution. |
| [`HostEntry`](/yosoi/python-api/map/types/host-entry/) | An admitted hostname with explicit reachability evidence. |
| [`MapOutcome`](/yosoi/python-api/map/types/map-outcome/) | Bounded discovery evidence with retained acquisition owners. |
| [`MapRequest`](/yosoi/python-api/map/types/map-request/) | Authored seed intent with validation deferred to checking or sending. |
| [`MapTermination`](/yosoi/python-api/map/types/map-termination/) | Why discovery stopped, independently of individual source success. |
| [`Observation`](/yosoi/python-api/map/types/observation/) | One retained provenance observation, without a reachability guarantee. |
| [`Omission`](/yosoi/python-api/map/types/omission/) | Counted omission events, not all undiscovered site items. |
| [`OmissionReason`](/yosoi/python-api/map/types/omission-reason/) | Classification of omitted discovery evidence or exploration work. |
| [`PageEntry`](/yosoi/python-api/map/types/page-entry/) | Normalized page URL with discovery and exploration evidence. |
| [`PublicProvider`](/yosoi/python-api/map/types/public-provider/) | Anonymous historical discovery indexes with fixed endpoint shapes. |
| [`Relationship`](/yosoi/python-api/map/types/relationship/) | Directed discovery evidence without merging the endpoint pages. |
| [`RequestTrace`](/yosoi/python-api/map/types/request-trace/) | Bounded acquisition accounting retained for a Map request. |
| [`RetainedCapture`](/yosoi/python-api/map/types/retained-capture/) | An acquired response kept alive with its owning Map outcome. |
| [`SourceFailure`](/yosoi/python-api/map/types/source-failure/) | Typed acquisition or parsing failure without raw response excerpts. |
| [`SourceOutcome`](/yosoi/python-api/map/types/source-outcome/) | Execution facts for one selected discovery source. |
| [`SourceStatus`](/yosoi/python-api/map/types/source-status/) | Per-source processing state, distinct from operation termination. |
| [`Summary`](/yosoi/python-api/map/types/summary/) | Recorded resource accounting and concurrency peaks for a discovery run. |
| [`SupportDocument`](/yosoi/python-api/map/types/support-document/) | A robots or sitemap support source and its execution state. |
| [`TreeEntry`](/yosoi/python-api/map/types/tree-entry/) | A page position in the deterministic rooted discovery forest. |
| [`WildcardEntry`](/yosoi/python-api/map/types/wildcard-entry/) | A retained wildcard pattern without expansion into guessed hosts. |

## Functions

| Name | Summary |
| --- | --- |
| [`compare_values`](/yosoi/python-api/map/functions/compare-values/) | Compare typed Map values with the public Rust `Ord` implementation. |
| [`new`](/yosoi/python-api/map/functions/new/) | Author seed intent without URL validation or network I/O. |
| [`rejection_message`](/yosoi/python-api/map/functions/rejection-message/) | Return the public Rust Display message without changing its wire tag. |

## Aliases

| Name | Summary |
| --- | --- |
| [`MapOrderingKind`](/yosoi/python-api/map/aliases/map-ordering-kind/) | Rust ordering contracts for discovery sources, provenance, omissions, providers, rejection codes, and relationships. This is declaration/struct ordering, not ordinary string sorting. |
| [`Rejection`](/yosoi/python-api/map/aliases/rejection/) | Admission classifications for invalid URLs, credentials, scope exclusions, filters, and byte/host limits. Rejection is separate from acquisition failure. |
| [`RelationshipKind`](/yosoi/python-api/map/aliases/relationship-kind/) | Directed link, redirect, or canonical-hint evidence. Links add rooted depth, redirects preserve depth, and canonical hints do not create traversal parents. |
| [`SkipReason`](/yosoi/python-api/map/aliases/skip-reason/) | Why an inventoried page was skipped: depth, robots rules, non-HTML content, or resource budget. Discovery alone does not imply exploration. |
| [`SourceSkipReason`](/yosoi/python-api/map/aliases/source-skip-reason/) | Source classification for a probe intentionally omitted because it was not a sitemap; this is not a successful sitemap parse. |
