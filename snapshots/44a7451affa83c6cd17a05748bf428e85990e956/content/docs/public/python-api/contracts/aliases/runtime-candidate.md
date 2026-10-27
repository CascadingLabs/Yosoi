---
title: "RuntimeCandidate"
description: "yosoi.contracts.RuntimeCandidate Python API reference."
order: 0
---

`yosoi.contracts.RuntimeCandidate`

```python
RuntimeCandidate = _runtime_contracts.RuntimeCandidate
```

Retain raw findings for every field of one runtime candidate.

Findings have not yet passed cardinality or value conversion checks.

Attributes:
    document_id: Identity of the document whose evidence was grouped.
    region: Grouping region lineage, or None for an ungrouped candidate.
    fields: Read-only field-to-findings mapping, including empty tuples for missing
        evidence.

[Source: python/yosoi/contracts.py:1562](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L1562-L1562)

[Definition](/yosoi/python-api/runtime-contracts/types/runtime-candidate/)

[Source: python/yosoi/runtime_contracts.py:36](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/runtime_contracts.py#L36-L73)
