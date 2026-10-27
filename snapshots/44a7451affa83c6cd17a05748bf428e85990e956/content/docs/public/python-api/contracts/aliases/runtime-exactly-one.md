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

[Source: python/yosoi/contracts.py:1572](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L1572-L1572)

[Definition](/yosoi/python-api/runtime-contracts/types/runtime-exactly-one/)

[Source: python/yosoi/runtime_contracts.py:92](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/runtime_contracts.py#L92-L102)
