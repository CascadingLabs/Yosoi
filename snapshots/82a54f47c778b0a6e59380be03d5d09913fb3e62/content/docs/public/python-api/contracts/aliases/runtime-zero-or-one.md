---
title: "RuntimeZeroOrOne"
description: "yosoi.contracts.RuntimeZeroOrOne Python API reference."
order: 0
---

`yosoi.contracts.RuntimeZeroOrOne`

```python
RuntimeZeroOrOne = _runtime_contracts.RuntimeZeroOrOne
```

Carry an optional field after cardinality and conversion checks.

Attributes:
    cardinality: Wire discriminator for zero-or-one cardinality.
    value: Validated value, or None when the optional field has no evidence.

[Source: python/yosoi/contracts.py:1010](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/contracts.py#L1010-L1010)

[Definition](/yosoi/python-api/runtime-contracts/types/runtime-zero-or-one/)

[Source: python/yosoi/runtime_contracts.py:120](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/runtime_contracts.py#L120-L129)
