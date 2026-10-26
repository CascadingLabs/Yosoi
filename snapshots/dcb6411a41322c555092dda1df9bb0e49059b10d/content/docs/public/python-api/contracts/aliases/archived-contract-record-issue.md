---
title: "ArchivedContractRecordIssue"
description: "yosoi.contracts.ArchivedContractRecordIssue Python API reference."
order: 0
---

`yosoi.contracts.ArchivedContractRecordIssue`

```python
ArchivedContractRecordIssue = _runtime_contracts.ArchivedContractRecordIssue
```

Retain a rejected portable candidate with its field issues.

Attributes:
    document_id: Identity of the source document.
    region: Grouping region lineage, or None for an ungrouped candidate.
    candidate_fields: Original findings grouped by schema field ID.
    fields: Reasons the candidate did not become an accepted record.

[Source: python/yosoi/contracts.py:1566](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L1566-L1566)

[Definition](/yosoi/python-api/runtime-contracts/types/archived-contract-record-issue/)

[Source: python/yosoi/runtime_contracts.py:262](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L262-L275)
