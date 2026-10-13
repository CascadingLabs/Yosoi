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

[Source: python/yosoi/runtime_contracts.py:132](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L132-L141)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
cardinality: Literal['many']
values: tuple[RuntimeValue, ...]
```
