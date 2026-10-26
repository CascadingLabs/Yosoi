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

[Source: python/yosoi/runtime_contracts.py:374](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/runtime_contracts.py#L374-L379)
