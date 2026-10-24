---
title: "RuntimeZeroOrOne"
description: "yosoi.runtime_contracts.RuntimeZeroOrOne Python API reference."
order: 0
---

`yosoi.runtime_contracts.RuntimeZeroOrOne`

```python
class RuntimeZeroOrOne(ImmutableModel):
```

Carry an optional field after cardinality and conversion checks.

Attributes:
    cardinality: Wire discriminator for zero-or-one cardinality.
    value: Validated value, or None when the optional field has no evidence.

[Source: python/yosoi/runtime_contracts.py:120](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L120-L129)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
cardinality: Literal['zero_or_one']
value: RuntimeValue | None
```
