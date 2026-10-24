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

[Source: python/yosoi/contracts.py:1633](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/contracts.py#L1633-L1633)

[Definition](/yosoi/python-api/runtime-contracts/types/runtime-exactly-one/)

[Source: python/yosoi/runtime_contracts.py:107](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/runtime_contracts.py#L107-L117)
