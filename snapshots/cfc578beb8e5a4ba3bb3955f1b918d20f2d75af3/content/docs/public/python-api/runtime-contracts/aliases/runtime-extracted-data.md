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

[Source: python/yosoi/runtime_contracts.py:698](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L698-L705)
