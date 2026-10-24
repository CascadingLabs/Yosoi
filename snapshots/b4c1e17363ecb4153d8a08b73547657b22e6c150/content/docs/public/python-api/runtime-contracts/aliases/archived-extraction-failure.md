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

[Source: python/yosoi/runtime_contracts.py:342](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/runtime_contracts.py#L342-L348)
