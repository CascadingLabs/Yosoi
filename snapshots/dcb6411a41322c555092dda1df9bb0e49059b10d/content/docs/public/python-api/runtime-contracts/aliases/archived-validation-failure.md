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

[Source: python/yosoi/runtime_contracts.py:342](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L342-L347)
