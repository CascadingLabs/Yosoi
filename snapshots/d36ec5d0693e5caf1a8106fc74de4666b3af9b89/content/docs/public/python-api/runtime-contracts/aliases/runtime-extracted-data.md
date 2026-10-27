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

[Source: python/yosoi/runtime_contracts.py:666](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L666-L673)
