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
    value_type: Native transport type, string. Python Contracts map
        other annotations to string and validate raw findings in Pydantic.

[Source: python/yosoi/contracts.py:115](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/contracts.py#L115-L134)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: FieldId
description: str
cardinality: Cardinality
value_type: str
```
