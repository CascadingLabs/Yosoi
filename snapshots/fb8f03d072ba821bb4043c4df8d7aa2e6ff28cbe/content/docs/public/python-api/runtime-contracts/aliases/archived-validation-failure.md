---
title: "ArchivedValidationFailure"
description: "yosoi.runtime_contracts.ArchivedValidationFailure Python API reference."
order: 0
---

`yosoi.runtime_contracts.ArchivedValidationFailure`

```python
type ArchivedValidationFailure = Annotated[_ArchivedInvalidSchema | _ArchivedValidationOverflow | _ArchivedValidationLimitExceeded, Field(discriminator='kind')]
```

Portable schema, counting, or validation-budget rejection.

[Source: python/yosoi/runtime_contracts.py:374](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/runtime_contracts.py#L374-L379)
