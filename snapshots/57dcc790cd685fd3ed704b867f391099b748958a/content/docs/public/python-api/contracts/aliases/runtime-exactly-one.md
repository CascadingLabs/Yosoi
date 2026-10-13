---
title: "RuntimeExactlyOne"
description: "yosoi.contracts.RuntimeExactlyOne Python API reference."
order: 0
---

`yosoi.contracts.RuntimeExactlyOne`

```python
RuntimeExactlyOne = _runtime_contracts.RuntimeExactlyOne
```

Carry the single value accepted for a required field.

Attributes:
    cardinality: Wire discriminator for exactly-one cardinality.
    value: Validated value; missing or repeated evidence cannot produce this
        variant.

[Source: python/yosoi/contracts.py:999](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L999-L999)

[Definition](/yosoi/python-api/runtime-contracts/types/runtime-exactly-one/)

[Source: python/yosoi/runtime_contracts.py:107](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L107-L117)
