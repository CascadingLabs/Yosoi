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

[Source: python/yosoi/runtime_contracts.py:107](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L107-L117)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
cardinality: Literal['exactly_one']
value: RuntimeValue
```
