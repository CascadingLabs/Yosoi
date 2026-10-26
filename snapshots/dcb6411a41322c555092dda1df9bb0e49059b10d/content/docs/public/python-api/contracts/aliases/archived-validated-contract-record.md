---
title: "ArchivedValidatedContractRecord"
description: "yosoi.contracts.ArchivedValidatedContractRecord Python API reference."
order: 0
---

`yosoi.contracts.ArchivedValidatedContractRecord`

```python
ArchivedValidatedContractRecord = _runtime_contracts.ArchivedValidatedContractRecord
```

Retain accepted portable values together with source evidence.

Attributes:
    document_id: Identity of the source document.
    region: Grouping region lineage, or None for an ungrouped record.
    fields: Accepted field values in the portable archive representation.
    evidence: Original per-field findings accompanying the accepted values.

[Source: python/yosoi/contracts.py:1569](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L1569-L1569)

[Definition](/yosoi/python-api/runtime-contracts/types/archived-validated-contract-record/)

[Source: python/yosoi/runtime_contracts.py:246](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L246-L259)
