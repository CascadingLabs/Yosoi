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

[Source: python/yosoi/contracts.py:988](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L988-L988)

[Definition](/yosoi/python-api/runtime-contracts/types/runtime-candidate/)

[Source: python/yosoi/runtime_contracts.py:37](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L37-L74)
