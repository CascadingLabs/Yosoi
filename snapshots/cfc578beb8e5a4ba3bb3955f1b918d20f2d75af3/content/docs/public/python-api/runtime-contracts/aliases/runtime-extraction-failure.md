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

[Source: python/yosoi/runtime_contracts.py:618](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L618-L624)
