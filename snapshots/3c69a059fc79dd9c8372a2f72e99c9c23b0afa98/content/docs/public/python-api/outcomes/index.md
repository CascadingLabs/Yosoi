---
title: "yosoi.outcomes"
description: "Public declarations in yosoi.outcomes."
order: 0
---

`yosoi.outcomes`

Typed locator outcomes preserve Rust evidence and terminal distinctions.

[Source: python/yosoi/outcomes.py:1](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/outcomes.py#L1-L1)

## Types

| Name | Summary |
| --- | --- |
| [`AccessibilityCoordinate`](/yosoi/python-api/outcomes/types/accessibility-coordinate/) | Accessibility node identity scoped to an immutable snapshot epoch. |
| [`AccessibilityLocation`](/yosoi/python-api/outcomes/types/accessibility-location/) | Tagged accessibility node evidence within a snapshot epoch. |
| [`Attribute`](/yosoi/python-api/outcomes/types/attribute/) | One projected attribute name and decoded value. |
| [`AttributeValue`](/yosoi/python-api/outcomes/types/attribute-value/) | Tagged attribute projection retaining its name as well as its value. |
| [`ByteRange`](/yosoi/python-api/outcomes/types/byte-range/) | Half-open byte offsets in an owned source payload, allowing empty ranges. |
| [`CapturedText`](/yosoi/python-api/outcomes/types/captured-text/) | Projected text and named regular-expression capture values. |
| [`Complete`](/yosoi/python-api/outcomes/types/complete/) | Evidence supports complete coverage of the requested locator scope. |
| [`DecodedTextCoordinate`](/yosoi/python-api/outcomes/types/decoded-text-coordinate/) | Paired source-byte and decoded-text scalar offsets for a match. |
| [`DecodedTextLocation`](/yosoi/python-api/outcomes/types/decoded-text-location/) | Tagged byte and Unicode-scalar evidence for a decoded-text match. |
| [`DomCoordinate`](/yosoi/python-api/outcomes/types/dom-coordinate/) | Rendered DOM node identity scoped to one immutable snapshot epoch. |
| [`ExpandedNamePathSegment`](/yosoi/python-api/outcomes/types/expanded-name-path-segment/) | Namespace-qualified XML element identity within a tree path. |
| [`Failure`](/yosoi/python-api/outcomes/types/failure/) | Typed terminal locator failure without hostile document excerpts. |
| [`Finding`](/yosoi/python-api/outcomes/types/finding/) | An ordered locator finding with projection and completeness evidence. |
| [`Indeterminate`](/yosoi/python-api/outcomes/types/indeterminate/) | No match was established and incomplete evidence prevents absence claims. |
| [`JsonLocation`](/yosoi/python-api/outcomes/types/json-location/) | Tagged JSON Pointer evidence, without proving document resolution. |
| [`JsonValueProjection`](/yosoi/python-api/outcomes/types/json-value-projection/) | Tagged JSON projection using Rust JSON value equality. |
| [`LocateFailed`](/yosoi/python-api/outcomes/types/locate-failed/) | Execution ended with a typed failure instead of a match or absence claim. |
| [`LocateResult`](/yosoi/python-api/outcomes/types/locate-result/) | Nonempty matched regions or findings in deterministic global order. |
| [`Matched`](/yosoi/python-api/outcomes/types/matched/) | At least one region or finding matched, possibly with partial evidence. |
| [`NoMatch`](/yosoi/python-api/outcomes/types/no-match/) | Complete locator execution found no match within the requested scope. |
| [`NodeReference`](/yosoi/python-api/outcomes/types/node-reference/) | Document-bound native location, without retaining document contents. |
| [`NodeValue`](/yosoi/python-api/outcomes/types/node-value/) | Tagged document-bound node reference rather than a content copy. |
| [`Partial`](/yosoi/python-api/outcomes/types/partial/) | Known evidence loss prevents an unqualified complete absence claim. |
| [`RegionLineage`](/yosoi/python-api/outcomes/types/region-lineage/) | Parent repeated-region identity and location for a finding. |
| [`RenderedDomLocation`](/yosoi/python-api/outcomes/types/rendered-dom-location/) | Tagged rendered-DOM node evidence within a snapshot epoch. |
| [`SourceTreeLocation`](/yosoi/python-api/outcomes/types/source-tree-location/) | Tagged HTML/XML tree evidence for a native finding coordinate. |
| [`TextRange`](/yosoi/python-api/outcomes/types/text-range/) | Half-open Unicode-scalar offsets in decoded text, allowing empty ranges. |
| [`TextValue`](/yosoi/python-api/outcomes/types/text-value/) | Owned decoded text emitted by a text projection. |
| [`TextWithCaptures`](/yosoi/python-api/outcomes/types/text-with-captures/) | Tagged text projection with named regular-expression captures. |
| [`TreeCoordinate`](/yosoi/python-api/outcomes/types/tree-coordinate/) | Source-tree location with optional byte and expanded-name evidence. |
| [`Unknown`](/yosoi/python-api/outcomes/types/unknown/) | Evidence completeness could not be established for the requested scope. |

## Functions

| Name | Summary |
| --- | --- |
| [`projected_values_equal`](/yosoi/python-api/outcomes/functions/projected-values-equal/) | Compare complete projection values with the Rust SDK's equality rules. |
| [`projected_values_not_equal`](/yosoi/python-api/outcomes/functions/projected-values-not-equal/) | Return the complementary Rust projection comparison. |

## Aliases

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

## Constants

| Name | Summary |
| --- | --- |
| [`U32`](/yosoi/python-api/outcomes/constants/u32/) | Strict integer from zero through the u32 maximum. Booleans, floating-point values, and numeric strings are not coerced. |
| [`U64`](/yosoi/python-api/outcomes/constants/u64/) | Strict integer from zero through the u64 maximum, without numeric coercion. Units and evidence meaning belong to the consuming field. |
