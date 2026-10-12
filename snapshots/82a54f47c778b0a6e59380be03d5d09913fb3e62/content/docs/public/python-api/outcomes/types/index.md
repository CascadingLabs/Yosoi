---
title: "Types"
description: "Types declared in yosoi.outcomes."
order: 0
---

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
