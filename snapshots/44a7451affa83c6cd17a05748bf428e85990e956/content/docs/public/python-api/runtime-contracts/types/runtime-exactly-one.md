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

[Source: python/yosoi/runtime_contracts.py:92](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/runtime_contracts.py#L92-L102)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
cardinality: Literal['exactly_one']
value: RuntimeValue
```
