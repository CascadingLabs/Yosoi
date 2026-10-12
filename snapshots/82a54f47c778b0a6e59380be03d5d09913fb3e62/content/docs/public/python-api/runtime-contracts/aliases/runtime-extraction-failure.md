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

[Source: python/yosoi/runtime_contracts.py:618](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/runtime_contracts.py#L618-L624)
