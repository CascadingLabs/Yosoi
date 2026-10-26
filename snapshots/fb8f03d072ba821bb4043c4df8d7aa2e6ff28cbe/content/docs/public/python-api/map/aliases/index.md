---
title: "Aliases"
description: "Aliases declared in yosoi.map."
order: 0
---

| Name | Summary |
| --- | --- |
| [`MapOrderingKind`](/yosoi/python-api/map/aliases/map-ordering-kind/) | Rust ordering contracts for discovery sources, provenance, omissions, providers, rejection codes, and relationships. This is declaration/struct ordering, not ordinary string sorting. |
| [`Rejection`](/yosoi/python-api/map/aliases/rejection/) | Admission classifications for invalid URLs, credentials, scope exclusions, filters, and byte/host limits. Rejection is separate from acquisition failure. |
| [`RelationshipKind`](/yosoi/python-api/map/aliases/relationship-kind/) | Directed link, redirect, or canonical-hint evidence. Links add rooted depth, redirects preserve depth, and canonical hints do not create traversal parents. |
| [`SkipReason`](/yosoi/python-api/map/aliases/skip-reason/) | Why an inventoried page was skipped: depth, robots rules, non-HTML content, or resource budget. Discovery alone does not imply exploration. |
| [`SourceSkipReason`](/yosoi/python-api/map/aliases/source-skip-reason/) | Source classification for a probe intentionally omitted because it was not a sitemap; this is not a successful sitemap parse. |
