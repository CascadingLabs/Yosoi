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

[Source: python/yosoi/contracts.py:1571](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L1571-L1571)

[Definition](/yosoi/python-api/runtime-contracts/types/runtime-contract-outcome/)

[Source: python/yosoi/runtime_contracts.py:869](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/runtime_contracts.py#L869-L1012)
