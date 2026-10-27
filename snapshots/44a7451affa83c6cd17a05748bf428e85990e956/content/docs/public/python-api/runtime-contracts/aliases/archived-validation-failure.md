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

[Source: python/yosoi/runtime_contracts.py:342](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/runtime_contracts.py#L342-L347)
