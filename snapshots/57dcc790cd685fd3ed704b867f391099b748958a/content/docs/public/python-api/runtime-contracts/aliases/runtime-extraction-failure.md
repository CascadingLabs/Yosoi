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

[Source: python/yosoi/runtime_contracts.py:618](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L618-L624)
