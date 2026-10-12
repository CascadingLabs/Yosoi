---
title: "Aliases"
description: "Aliases declared in yosoi.locators."
order: 0
---

| Name | Summary |
| --- | --- |
| [`AccessibilityStateName`](/yosoi/python-api/locators/aliases/accessibility-state-name/) | Supported boolean accessibility snapshot state names: expanded and focused. These queries do not mutate a live browser. |
| [`JsonQuerySyntaxError`](/yosoi/python-api/locators/aliases/json-query-syntax-error/) | Exact Rust JSON-query syntax classifications, separating invalid pointers, invalid paths, and unsupported path features. |
| [`NamedOutput`](/yosoi/python-api/locators/aliases/named-output/) | Alias for an Output declaration pairing an authored identity with its query and projection. Output identity uniqueness is checked when a Plan is compiled. |
| [`OutputPlan`](/yosoi/python-api/locators/aliases/output-plan/) | Alias for the query-plus-projection Locator declaration. A compiled collection of named outputs is represented by Plan instead. |
| [`ProjectionKind`](/yosoi/python-api/locators/aliases/projection-kind/) | Projection vocabulary preserving text, attributes, JSON values, node references, accessible names, and named captures. Query/projection compatibility is checked by Rust. |
| [`QueryKind`](/yosoi/python-api/locators/aliases/query-kind/) | Authored query vocabularies for trees, JSON, accessibility snapshots, and decoded text. Document capabilities and execution limits are checked separately. |
| [`QueryResultShape`](/yosoi/python-api/locators/aliases/query-result-shape/) | Portable result capabilities: tree nodes, JSON values, accessibility nodes, or text ranges. Shape is distinct from match count or evidence completeness. |
| [`RegionPlan`](/yosoi/python-api/locators/aliases/region-plan/) | Alias for a repeated-region declaration carrying a root query and lineage identity. Nested repeated regions are unsupported. |
