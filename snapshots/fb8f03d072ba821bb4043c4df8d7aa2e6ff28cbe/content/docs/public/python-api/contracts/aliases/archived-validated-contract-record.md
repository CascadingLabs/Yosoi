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

[Source: python/yosoi/contracts.py:1630](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/contracts.py#L1630-L1630)

[Definition](/yosoi/python-api/runtime-contracts/types/archived-validated-contract-record/)

[Source: python/yosoi/runtime_contracts.py:278](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/runtime_contracts.py#L278-L291)
