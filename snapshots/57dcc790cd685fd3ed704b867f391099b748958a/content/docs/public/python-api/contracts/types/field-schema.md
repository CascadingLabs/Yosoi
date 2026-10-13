---
title: "FieldSchema"
description: "yosoi.contracts.FieldSchema Python API reference."
order: 0
---

`yosoi.contracts.FieldSchema`

```python
class FieldSchema(ImmutableModel):
```

Rust-validated field meaning, cardinality, and type metadata.

Attributes:
    id: Authored identifier matching locator output evidence.
    description: Nonblank business meaning; it does not discover a locator.
    cardinality: exactly_one, zero_or_one, or many constrains validation, not
        extraction.
    value_type: Nonblank conversion identifier; runtime Contracts support string and
        money.usd.

[Source: python/yosoi/contracts.py:135](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L135-L155)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: FieldId
description: str
cardinality: Cardinality
value_type: str
```
