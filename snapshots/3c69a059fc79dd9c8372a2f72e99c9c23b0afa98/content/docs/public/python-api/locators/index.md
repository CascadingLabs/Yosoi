---
title: "yosoi.locators"
description: "Public declarations in yosoi.locators."
order: 0
---

`yosoi.locators`

Pydantic locator authoring; Rust compiles and executes every plan.

[Source: python/yosoi/locators.py:1](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/locators.py#L1-L1)

## Types

| Name | Summary |
| --- | --- |
| [`AccessibilityStateAtom`](/yosoi/python-api/locators/types/accessibility-state-atom/) | One supported boolean accessibility-state query operand. |
| [`Locator`](/yosoi/python-api/locators/types/locator/) | Query intent paired with an explicit supported projection. |
| [`NamespaceBinding`](/yosoi/python-api/locators/types/namespace-binding/) | Query-local XML namespace binding independent of source prefixes. |
| [`Output`](/yosoi/python-api/locators/types/output/) | Named projected evidence declaration for a compiled locate plan. |
| [`Plan`](/yosoi/python-api/locators/types/plan/) | Compiled immutable outputs and repeated-region declarations. |
| [`Query`](/yosoi/python-api/locators/types/query/) | Immutable locator intent compiled and checked by the Rust SDK. |
| [`QueryAtom`](/yosoi/python-api/locators/types/query-atom/) | Closed portable query meaning, separate from Python authoring syntax. |
| [`QuerySpec`](/yosoi/python-api/locators/types/query-spec/) | Portable Rust query semantics with validated result shape. |
| [`Region`](/yosoi/python-api/locators/types/region/) | One authored repeated-region query and its lineage identity. |

## Functions

| Name | Summary |
| --- | --- |
| [`accessibility_state`](/yosoi/python-api/locators/functions/accessibility-state/) | Declare a boolean accessibility-state query without browser I/O. |
| [`accessibility_text`](/yosoi/python-api/locators/functions/accessibility-text/) | Author accessibility node text query intent without document I/O. |
| [`accessible_name`](/yosoi/python-api/locators/functions/accessible-name/) | Author accessible node name query intent without document I/O. |
| [`css`](/yosoi/python-api/locators/functions/css/) | Author CSS tree-node query intent without document I/O. |
| [`json_path`](/yosoi/python-api/locators/functions/json-path/) | Author supported Rust JSONPath value query intent without document I/O. |
| [`json_pointer`](/yosoi/python-api/locators/functions/json-pointer/) | Author JSON Pointer value query intent without document I/O. |
| [`output`](/yosoi/python-api/locators/functions/output/) | Name one explicit query and projection declaration. |
| [`regex`](/yosoi/python-api/locators/functions/regex/) | Author decoded-text regular-expression range query intent without document I/O. |
| [`role`](/yosoi/python-api/locators/functions/role/) | Author accessibility role query intent without document I/O. |
| [`text_literal`](/yosoi/python-api/locators/functions/text-literal/) | Author decoded-text literal range query intent without document I/O. |
| [`tree_text_contains`](/yosoi/python-api/locators/functions/tree-text-contains/) | Author tree descendant-text substring query intent without document I/O. |
| [`xpath`](/yosoi/python-api/locators/functions/xpath/) | Author XPath tree-node query intent without document I/O. |

## Aliases

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
