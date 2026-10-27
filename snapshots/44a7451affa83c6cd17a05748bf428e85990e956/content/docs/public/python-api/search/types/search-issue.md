---
title: "SearchIssue"
description: "yosoi.search.SearchIssue Python API reference."
order: 0
---

`yosoi.search.SearchIssue`

```python
class SearchIssue(ImmutableModel):
```

A bounded structural extraction issue without raw response excerpts.

Attributes:
    placement_index: One-based affected placement, or None for a response-wide
        issue.
    kind: Classifies invalid or duplicate destinations, missing fields, unrecognized
        rows, output limits, or query relaxation. Inspect coverage before claiming
        completeness.

[Source: python/yosoi/search.py:332](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/search.py#L332-L351)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
placement_index: Rank | None
kind: Literal['invalid_destination', 'duplicate_destination', 'missing_required_field', 'unrecognized_result_row', 'output_limit', 'query_relaxed']
```
