---
title: "JsonCoordinate"
description: "yosoi.scalars.JsonCoordinate Python API reference."
order: 0
---

`yosoi.scalars.JsonCoordinate`

```python
class JsonCoordinate(ValidatedString):
```

Validated JSON Pointer spelling without checking document resolution.

[Source: python/yosoi/scalars.py:228](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/scalars.py#L228-L235)

## Base classes

[ValidatedString](/yosoi/python-api/scalars/types/validated-string/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### as_pointer

```python
def as_pointer(self) -> str:
```

Return validated pointer spelling; the empty pointer denotes the root.

[Source: python/yosoi/scalars.py:233](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/scalars.py#L233-L235)
