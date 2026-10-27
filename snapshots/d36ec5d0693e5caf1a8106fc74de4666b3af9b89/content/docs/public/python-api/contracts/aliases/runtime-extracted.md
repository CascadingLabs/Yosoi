---
title: "RuntimeExtracted"
description: "yosoi.contracts.RuntimeExtracted Python API reference."
order: 0
---

`yosoi.contracts.RuntimeExtracted`

```python
RuntimeExtracted = _runtime_contracts.RuntimeExtracted
```

Inspect runtime extraction results while retaining the Rust handle.

The Python view includes empty tuples for missing candidate fields. JSON
serialization preserves the original Rust wire, which may omit those entries.

Attributes:
    contract_schema: Schema used to interpret and complete candidate field mappings.
    view: Immutable status-tagged extraction DTO with every schema field
        represented.

[Source: python/yosoi/contracts.py:1573](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/contracts.py#L1573-L1573)

[Definition](/yosoi/python-api/runtime-contracts/types/runtime-extracted/)

[Source: python/yosoi/runtime_contracts.py:754](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L754-L866)
