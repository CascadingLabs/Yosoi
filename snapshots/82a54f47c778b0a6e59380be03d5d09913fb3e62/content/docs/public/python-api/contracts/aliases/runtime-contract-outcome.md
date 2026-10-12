---
title: "RuntimeContractOutcome"
description: "yosoi.contracts.RuntimeContractOutcome Python API reference."
order: 0
---

`yosoi.contracts.RuntimeContractOutcome`

```python
RuntimeContractOutcome = _runtime_contracts.RuntimeContractOutcome
```

Inspect runtime validation results while retaining the Rust handle.

The Python view includes empty tuples for missing candidate fields. JSON
serialization preserves the original Rust wire, which may omit those entries.

Attributes:
    contract_schema: Schema used to interpret and complete candidate field mappings.
    view: Immutable status-tagged validation DTO with every schema field
        represented.

[Source: python/yosoi/contracts.py:998](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/contracts.py#L998-L998)

[Definition](/yosoi/python-api/runtime-contracts/types/runtime-contract-outcome/)

[Source: python/yosoi/runtime_contracts.py:901](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/runtime_contracts.py#L901-L1044)
