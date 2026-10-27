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

[Source: python/yosoi/runtime_contracts.py:626](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/runtime_contracts.py#L626-L629)
