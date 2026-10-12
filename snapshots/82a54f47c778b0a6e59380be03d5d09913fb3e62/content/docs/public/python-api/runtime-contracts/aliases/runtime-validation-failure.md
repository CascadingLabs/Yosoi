---
title: "RuntimeValidationFailure"
description: "yosoi.runtime_contracts.RuntimeValidationFailure Python API reference."
order: 0
---

`yosoi.runtime_contracts.RuntimeValidationFailure`

```python
type RuntimeValidationFailure = Annotated[_InvalidValidationSchema | _ValidationOverflow | _ValidationLimitExceeded, Field(discriminator='kind')]
```

Typed schema, counting, or validation-budget rejection.

[Source: python/yosoi/runtime_contracts.py:658](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/runtime_contracts.py#L658-L661)
