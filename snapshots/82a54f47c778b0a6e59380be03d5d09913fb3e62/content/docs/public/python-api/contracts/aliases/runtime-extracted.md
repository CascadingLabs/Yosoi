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

[Source: python/yosoi/contracts.py:1000](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/contracts.py#L1000-L1000)

[Definition](/yosoi/python-api/runtime-contracts/types/runtime-extracted/)

[Source: python/yosoi/runtime_contracts.py:786](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/runtime_contracts.py#L786-L898)
