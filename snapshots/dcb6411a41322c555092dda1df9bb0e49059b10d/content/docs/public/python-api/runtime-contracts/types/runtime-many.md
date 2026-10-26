---
title: "RuntimeMany"
description: "yosoi.runtime_contracts.RuntimeMany Python API reference."
order: 0
---

`yosoi.runtime_contracts.RuntimeMany`

```python
class RuntimeMany(ImmutableModel):
```

Carry all accepted values for a repeated field.

Attributes:
    cardinality: Wire discriminator for many cardinality.
    values: Ordered validated values; an empty tuple is permitted.

[Source: python/yosoi/runtime_contracts.py:117](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L117-L126)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
cardinality: Literal['many']
values: tuple[RuntimeValue, ...]
```
