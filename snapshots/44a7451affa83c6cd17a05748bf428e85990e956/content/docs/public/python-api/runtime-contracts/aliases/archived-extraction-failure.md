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

[Source: python/yosoi/runtime_contracts.py:310](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/runtime_contracts.py#L310-L316)
