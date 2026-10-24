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

[Source: python/yosoi/contracts.py:340](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/contracts.py#L340-L369)

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

[Source: python/yosoi/contracts.py:353](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/contracts.py#L353-L355)

### is_absent

```python
@property
def is_absent(self) -> bool:
```

Return whether no findings are retained, without an absence claim.

[Source: python/yosoi/contracts.py:358](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/contracts.py#L358-L360)

### is_empty

```python
@property
def is_empty(self) -> bool:
```

Return whether evidence is empty, independently of completeness.

[Source: python/yosoi/contracts.py:363](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/contracts.py#L363-L365)
