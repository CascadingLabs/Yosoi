---
title: "JsonLocation"
description: "yosoi.outcomes.JsonLocation Python API reference."
order: 0
---

`yosoi.outcomes.JsonLocation`

```python
class JsonLocation(ImmutableModel):
```

Tagged JSON Pointer evidence, without proving document resolution.

Attributes:
    kind: Discriminator fixed to json for tagged decoding.
    coordinate: Validated pointer spelling; an empty pointer denotes the root.

[Source: python/yosoi/outcomes.py:417](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/outcomes.py#L417-L426)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['json']
coordinate: JsonCoordinate
```
