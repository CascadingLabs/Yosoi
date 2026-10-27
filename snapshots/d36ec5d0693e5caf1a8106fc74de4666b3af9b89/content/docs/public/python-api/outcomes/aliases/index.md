---
title: "Aliases"
description: "Aliases declared in yosoi.outcomes."
order: 0
---

| Name | Summary |
| --- | --- |
| [`Completeness`](/yosoi/python-api/outcomes/aliases/completeness/) | Tagged complete, partial, or unknown coverage of requested evidence. Complete coverage is scoped to the operation, not an exhaustive claim about a site. |
| [`DocumentClassName`](/yosoi/python-api/outcomes/aliases/document-class-name/) | Serialized document capability names. Source HTML/XML/JSON/text, rendered DOM, and accessibility-tree evidence remain distinct. |
| [`IncompleteEvidence`](/yosoi/python-api/outcomes/aliases/incomplete-evidence/) | Partial or unknown evidence that cannot establish complete absence. Known loss and unestablished coverage remain distinct. |
| [`LocateFailure`](/yosoi/python-api/outcomes/aliases/locate-failure/) | Alias for typed structural locator failure details, separate from match, complete absence, or indeterminate evidence. |
| [`LocateOutcome`](/yosoi/python-api/outcomes/aliases/locate-outcome/) | Tagged matches, complete no-match, indeterminate evidence, or typed failure. An empty convenience list alone cannot distinguish these states. |
| [`NativeCoordinate`](/yosoi/python-api/outcomes/aliases/native-coordinate/) | Tagged representation-native location: source tree, JSON Pointer, rendered DOM, accessibility node, or decoded-text ranges. Interpret it with its document identity and epoch. |
| [`PositiveU32`](/yosoi/python-api/outcomes/aliases/positiveu32/) | Strict positive u32 integer. Zero and numeric coercions are rejected; units belong to the consuming field. |
| [`ProjectedValue`](/yosoi/python-api/outcomes/aliases/projected-value/) | Tagged text, captured text, attribute, JSON, or document-bound node value. Projection identity retains information omitted by convenience value accessors. |
| [`ResourceLimit`](/yosoi/python-api/outcomes/aliases/resource-limit/) | Locator resource classifications for byte, node, visit, query, region, match, capture, depth, and output accounting. Each named counter has its own units. |
