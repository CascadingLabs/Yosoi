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

[Source: python/yosoi/contracts.py:993](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L993-L993)

[Definition](/yosoi/python-api/runtime-contracts/types/archived-contract-record-issue/)

[Source: python/yosoi/runtime_contracts.py:294](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L294-L307)
