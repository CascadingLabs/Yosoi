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

[Source: python/yosoi/contracts.py:1627](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/contracts.py#L1627-L1627)

[Definition](/yosoi/python-api/runtime-contracts/types/archived-contract-record-issue/)

[Source: python/yosoi/runtime_contracts.py:294](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/runtime_contracts.py#L294-L307)
