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

[Source: python/yosoi/contracts.py:1644](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/contracts.py#L1644-L1644)

[Definition](/yosoi/python-api/runtime-contracts/types/runtime-zero-or-one/)

[Source: python/yosoi/runtime_contracts.py:120](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L120-L129)
