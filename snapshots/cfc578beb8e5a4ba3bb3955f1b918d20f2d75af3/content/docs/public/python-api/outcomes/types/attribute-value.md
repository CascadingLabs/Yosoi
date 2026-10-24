---
title: "AttributeValue"
description: "yosoi.outcomes.AttributeValue Python API reference."
order: 0
---

`yosoi.outcomes.AttributeValue`

```python
class AttributeValue(ImmutableModel):
```

Tagged attribute projection retaining its name as well as its value.

Attributes:
    kind: Discriminator fixed to attribute for tagged decoding.
    value: Projected attribute name and decoded text.

[Source: python/yosoi/outcomes.py:617](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/outcomes.py#L617-L626)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['attribute']
value: Attribute
```
