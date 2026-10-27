---
title: "JsonValueProjection"
description: "yosoi.outcomes.JsonValueProjection Python API reference."
order: 0
---

`yosoi.outcomes.JsonValueProjection`

```python
class JsonValueProjection(ImmutableModel):
```

Tagged JSON projection using Rust JSON value equality.

Attributes:
    kind: Discriminator fixed to json for tagged decoding.
    value: Retained native JSON shape; nonfinite numbers are rejected. Nested
        collections remain mutable despite frozen model attributes.

[Source: python/yosoi/outcomes.py:629](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/outcomes.py#L629-L663)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['json']
value: JsonValue
```
