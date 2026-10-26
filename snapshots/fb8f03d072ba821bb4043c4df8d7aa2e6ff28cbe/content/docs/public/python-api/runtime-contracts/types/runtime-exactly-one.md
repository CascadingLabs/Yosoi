---
title: "RuntimeExactlyOne"
description: "yosoi.runtime_contracts.RuntimeExactlyOne Python API reference."
order: 0
---

`yosoi.runtime_contracts.RuntimeExactlyOne`

```python
class RuntimeExactlyOne(ImmutableModel):
```

Carry the single value accepted for a required field.

Attributes:
    cardinality: Wire discriminator for exactly-one cardinality.
    value: Validated value; missing or repeated evidence cannot produce this
        variant.

[Source: python/yosoi/runtime_contracts.py:107](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/runtime_contracts.py#L107-L117)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
cardinality: Literal['exactly_one']
value: RuntimeValue
```
