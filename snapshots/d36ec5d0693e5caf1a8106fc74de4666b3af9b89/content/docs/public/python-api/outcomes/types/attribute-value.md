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

[Source: python/yosoi/outcomes.py:617](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/outcomes.py#L617-L626)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['attribute']
value: Attribute
```
