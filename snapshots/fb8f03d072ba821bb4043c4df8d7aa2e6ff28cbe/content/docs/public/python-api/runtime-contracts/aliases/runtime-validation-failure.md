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

[Source: python/yosoi/runtime_contracts.py:658](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/runtime_contracts.py#L658-L661)
