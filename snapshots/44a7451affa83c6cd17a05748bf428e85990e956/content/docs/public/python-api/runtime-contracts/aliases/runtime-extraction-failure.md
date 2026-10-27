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

[Source: python/yosoi/runtime_contracts.py:586](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/runtime_contracts.py#L586-L592)
