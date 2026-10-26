---
title: "Indeterminate"
description: "yosoi.outcomes.Indeterminate Python API reference."
order: 0
---

`yosoi.outcomes.Indeterminate`

```python
class Indeterminate(_Outcome):
```

No match was established and incomplete evidence prevents absence claims.

Attributes:
    status: Discriminator fixed to indeterminate for tagged decoding.
    document_id: Examined document identity.
    completeness: Partial or unknown evidence limiting the absence claim.
    reason_code: Structural explanation of why absence could not be established.

[Source: python/yosoi/outcomes.py:1010](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/outcomes.py#L1010-L1023)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['indeterminate']
document_id: DocumentId
completeness: IncompleteEvidence
reason_code: str
```
