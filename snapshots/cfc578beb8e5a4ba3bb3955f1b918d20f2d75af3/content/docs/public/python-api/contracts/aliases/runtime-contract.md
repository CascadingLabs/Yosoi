---
title: "RuntimeContract"
description: "yosoi.contracts.RuntimeContract Python API reference."
order: 0
---

`yosoi.contracts.RuntimeContract`

```python
RuntimeContract = _runtime_contracts.RuntimeContract
```

Author a Contract schema for extraction and validation in Rust.

The schema defines grouping, fields, cardinalities, and value types. Unsupported
conversions remain explicit validation issues rather than inferred Python
conversions.

Attributes:
    contract_schema: Public schema validated when the native Contract is
        constructed.

[Source: python/yosoi/contracts.py:1631](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/contracts.py#L1631-L1631)

[Definition](/yosoi/python-api/runtime-contracts/types/runtime-contract/)

[Source: python/yosoi/runtime_contracts.py:1047](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L1047-L1129)
