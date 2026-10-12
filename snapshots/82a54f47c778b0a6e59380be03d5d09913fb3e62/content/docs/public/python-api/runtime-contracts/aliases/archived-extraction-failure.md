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

[Source: python/yosoi/runtime_contracts.py:342](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/runtime_contracts.py#L342-L348)
