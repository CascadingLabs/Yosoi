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

[Source: python/yosoi/runtime_contracts.py:626](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L626-L629)
