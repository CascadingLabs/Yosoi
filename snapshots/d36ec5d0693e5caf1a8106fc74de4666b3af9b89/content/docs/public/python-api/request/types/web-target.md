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

[Source: python/yosoi/request.py:56](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/request.py#L56-L75)

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

[Source: python/yosoi/request.py:62](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/request.py#L62-L71)
