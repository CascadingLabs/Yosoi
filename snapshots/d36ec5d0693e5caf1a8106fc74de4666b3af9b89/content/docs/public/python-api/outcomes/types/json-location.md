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

[Source: python/yosoi/outcomes.py:417](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/outcomes.py#L417-L426)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['json']
coordinate: JsonCoordinate
```
