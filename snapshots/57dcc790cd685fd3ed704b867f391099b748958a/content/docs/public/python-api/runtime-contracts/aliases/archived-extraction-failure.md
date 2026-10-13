---
title: "ArchivedExtractionFailure"
description: "yosoi.runtime_contracts.ArchivedExtractionFailure Python API reference."
order: 0
---

`yosoi.runtime_contracts.ArchivedExtractionFailure`

```python
type ArchivedExtractionFailure = Annotated[_ArchivedInvalidSchema | _ArchivedExtractionCountOverflow | _ArchivedGroupingIndexInvariant | _ArchivedExtractionLimitExceeded, Field(discriminator='kind')]
```

Portable schema, counting, grouping, or extraction-budget rejection.

[Source: python/yosoi/runtime_contracts.py:342](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L342-L348)
