---
title: "TextValue"
description: "yosoi.outcomes.TextValue Python API reference."
order: 0
---

`yosoi.outcomes.TextValue`

```python
class TextValue(ImmutableModel):
```

Owned decoded text emitted by a text projection.

Attributes:
    kind: Discriminator fixed to text for tagged decoding.
    value: Complete projected text retained as a Python string.

[Source: python/yosoi/outcomes.py:568](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/outcomes.py#L568-L577)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['text']
value: str
```
