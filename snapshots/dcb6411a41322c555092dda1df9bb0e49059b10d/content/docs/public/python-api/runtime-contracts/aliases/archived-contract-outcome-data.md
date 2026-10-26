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

[Source: python/yosoi/runtime_contracts.py:390](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L390-L398)
