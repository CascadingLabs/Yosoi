---
title: "RuntimeContractOutcomeData"
description: "yosoi.runtime_contracts.RuntimeContractOutcomeData Python API reference."
order: 0
---

`yosoi.runtime_contracts.RuntimeContractOutcomeData`

```python
type RuntimeContractOutcomeData = Annotated[_RuntimeEvaluated | _RuntimeOutcomeNoMatch | _RuntimeOutcomeIndeterminate | _RuntimeOutcomeLocateFailed | _RuntimeExtractionRejected | _RuntimeValidationRejected, Field(discriminator='status')]
```

Validation variants retaining accepted records, issues, or phase failures.

[Source: python/yosoi/runtime_contracts.py:719](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L719-L727)
