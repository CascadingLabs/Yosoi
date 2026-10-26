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

[Source: python/yosoi/runtime_contracts.py:719](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L719-L727)
