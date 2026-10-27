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

[Source: python/yosoi/contracts.py:1582](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L1582-L1582)

[Definition](/yosoi/python-api/runtime-contracts/types/runtime-zero-or-one/)

[Source: python/yosoi/runtime_contracts.py:105](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/runtime_contracts.py#L105-L114)
