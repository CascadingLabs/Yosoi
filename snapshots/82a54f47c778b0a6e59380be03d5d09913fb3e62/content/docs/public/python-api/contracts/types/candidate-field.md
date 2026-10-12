---
title: "CandidateField"
description: "yosoi.contracts.CandidateField Python API reference."
order: 0
---

`yosoi.contracts.CandidateField`

```python
class CandidateField(ImmutableModel):
```

Ordered projection values and original findings before conversion.

Attributes:
    field_id: Authored identity of this candidate field.
    evidence: Retained findings, coordinates, and completeness. Empty evidence alone
        does not establish complete absence.

[Source: python/yosoi/contracts.py:294](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/contracts.py#L294-L323)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
field_id: FieldId
evidence: tuple[Finding, ...] = PydanticField(default=(), repr=False)
```

## Methods

### values

```python
@property
def values(self) -> tuple[ProjectedValue, ...]:
```

Return projection wrappers in evidence order without typed conversion.

[Source: python/yosoi/contracts.py:307](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/contracts.py#L307-L309)

### is_absent

```python
@property
def is_absent(self) -> bool:
```

Return whether no findings are retained, without an absence claim.

[Source: python/yosoi/contracts.py:312](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/contracts.py#L312-L314)

### is_empty

```python
@property
def is_empty(self) -> bool:
```

Return whether evidence is empty, independently of completeness.

[Source: python/yosoi/contracts.py:317](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/contracts.py#L317-L319)
