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

[Source: python/yosoi/runtime_contracts.py:751](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/runtime_contracts.py#L751-L759)
