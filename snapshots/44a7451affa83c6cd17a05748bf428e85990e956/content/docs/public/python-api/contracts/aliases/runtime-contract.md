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

[Source: python/yosoi/contracts.py:1570](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L1570-L1570)

[Definition](/yosoi/python-api/runtime-contracts/types/runtime-contract/)

[Source: python/yosoi/runtime_contracts.py:1015](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/runtime_contracts.py#L1015-L1097)
