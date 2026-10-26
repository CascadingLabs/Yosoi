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

[Source: python/yosoi/runtime_contracts.py:698](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/runtime_contracts.py#L698-L705)
