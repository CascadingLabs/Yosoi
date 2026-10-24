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

[Source: python/yosoi/runtime_contracts.py:658](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L658-L661)
