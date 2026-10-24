---
title: "ArchivedContractString"
description: "yosoi.runtime_contracts.ArchivedContractString Python API reference."
order: 0
---

`yosoi.runtime_contracts.ArchivedContractString`

```python
class ArchivedContractString(ImmutableModel):
```

Store a validated string in the portable archive format.

Attributes:
    type: Wire discriminator for archived string values.
    value: Retained string content; hidden from the default repr.

[Source: python/yosoi/runtime_contracts.py:211](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/runtime_contracts.py#L211-L220)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
type: Literal['string']
value: str = Field(repr=False)
```
