---
title: "WebTarget"
description: "yosoi.request.WebTarget Python API reference."
order: 0
---

`yosoi.request.WebTarget`

```python
class WebTarget(ValidatedString):
```

Authored request target; Rust defers URL validation until preparation.

[Source: python/yosoi/request.py:56](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/request.py#L56-L75)

## Base classes

[ValidatedString](/yosoi/python-api/scalars/types/validated-string/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### new

```python
@classmethod
def new(cls, value: str) -> WebTarget:
```

Retain target text without URL validation or network I/O.

Args:
    value: Original target text to validate during request preparation.

Returns:
    A string value whose construction does not prove that the URL is usable.

[Source: python/yosoi/request.py:62](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/request.py#L62-L71)
