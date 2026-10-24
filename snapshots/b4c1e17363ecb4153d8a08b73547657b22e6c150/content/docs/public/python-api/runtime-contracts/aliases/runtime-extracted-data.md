---
title: "RuntimeExtractedData"
description: "yosoi.runtime_contracts.RuntimeExtractedData Python API reference."
order: 0
---

`yosoi.runtime_contracts.RuntimeExtractedData`

```python
type RuntimeExtractedData = Annotated[_RuntimeCandidates | _RuntimeNoMatch | _RuntimeIndeterminate | _RuntimeLocateFailed | _RuntimeRejected, Field(discriminator='status')]
```

Extraction variants distinguishing candidates from incomplete or failed work.

[Source: python/yosoi/runtime_contracts.py:698](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/runtime_contracts.py#L698-L705)
