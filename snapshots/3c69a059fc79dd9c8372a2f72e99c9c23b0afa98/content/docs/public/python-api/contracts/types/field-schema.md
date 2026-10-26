---
title: "FieldSchema"
description: "yosoi.contracts.FieldSchema Python API reference."
order: 0
---

`yosoi.contracts.FieldSchema`

```python
class FieldSchema(ImmutableModel):
```

Native transport field meaning, cardinality, and scalar type metadata.

Attributes:
    id: Authored identifier matching locator output evidence.
    description: Nonblank business meaning; it does not discover a locator.
    cardinality: exactly_one, zero_or_one, or many describes candidate field shape.
    value_type: Native transport type, string or money.usd. Python Contracts map
        other annotations to string and validate raw findings in Pydantic.

[Source: python/yosoi/contracts.py:160](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L160-L179)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: FieldId
description: str
cardinality: Cardinality
value_type: str
```
