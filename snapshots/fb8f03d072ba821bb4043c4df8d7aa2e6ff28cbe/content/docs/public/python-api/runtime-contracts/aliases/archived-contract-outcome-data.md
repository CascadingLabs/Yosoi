---
title: "ArchivedContractOutcomeData"
description: "yosoi.runtime_contracts.ArchivedContractOutcomeData Python API reference."
order: 0
---

`yosoi.runtime_contracts.ArchivedContractOutcomeData`

```python
type ArchivedContractOutcomeData = Annotated[_ArchivedEvaluated | _ArchivedNoMatch | _ArchivedIndeterminate | _ArchivedLocateFailed | _ArchivedExtractionRejected | _ArchivedValidationRejected, Field(discriminator='status')]
```

Portable outcome variants tagged by evaluation or phase-failure status.

[Source: python/yosoi/runtime_contracts.py:422](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/runtime_contracts.py#L422-L430)
