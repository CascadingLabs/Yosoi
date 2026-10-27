---
title: "RuntimeExtractionFailure"
description: "yosoi.runtime_contracts.RuntimeExtractionFailure Python API reference."
order: 0
---

`yosoi.runtime_contracts.RuntimeExtractionFailure`

```python
type RuntimeExtractionFailure = Annotated[_InvalidSchemaFailure | _ExtractionCountOverflow | _GroupingIndexInvariant | _ExtractionLimitExceeded, Field(discriminator='kind')]
```

Typed schema, counting, grouping, or extraction-budget rejection.

[Source: python/yosoi/runtime_contracts.py:586](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L586-L592)
