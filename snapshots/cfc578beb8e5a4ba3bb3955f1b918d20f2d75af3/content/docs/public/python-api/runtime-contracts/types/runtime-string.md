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

[Source: python/yosoi/runtime_contracts.py:77](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L77-L86)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
type: Literal['string']
value: str
```
