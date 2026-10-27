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

[Source: python/yosoi/contracts.py:295](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/contracts.py#L295-L324)

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

[Source: python/yosoi/contracts.py:308](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/contracts.py#L308-L310)

### is_absent

```python
@property
def is_absent(self) -> bool:
```

Return whether no findings are retained, without an absence claim.

[Source: python/yosoi/contracts.py:313](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/contracts.py#L313-L315)

### is_empty

```python
@property
def is_empty(self) -> bool:
```

Return whether evidence is empty, independently of completeness.

[Source: python/yosoi/contracts.py:318](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/contracts.py#L318-L320)
