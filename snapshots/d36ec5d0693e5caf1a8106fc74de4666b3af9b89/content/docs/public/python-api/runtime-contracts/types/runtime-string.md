---
title: "RuntimeString"
description: "yosoi.runtime_contracts.RuntimeString Python API reference."
order: 0
---

`yosoi.runtime_contracts.RuntimeString`

```python
class RuntimeString(ImmutableModel):
```

Carry a string accepted by runtime Contract validation.

Attributes:
    type: Wire discriminator identifying a string value.
    value: Validated string content.

[Source: python/yosoi/runtime_contracts.py:76](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L76-L85)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
type: Literal['string']
value: str
```
