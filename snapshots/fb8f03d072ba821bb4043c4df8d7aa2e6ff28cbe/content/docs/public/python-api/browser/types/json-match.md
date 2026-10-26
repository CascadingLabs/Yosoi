---
title: "JsonMatch"
description: "yosoi.browser.JsonMatch Python API reference."
order: 0
---

`yosoi.browser.JsonMatch`

```python
class JsonMatch(ImmutableModel):
```

Compare a response JSON value at an RFC 6901 pointer.

Attributes:
    pointer: JSON Pointer; empty selects the root, and ~0/~1 escape tilde/slash.
    value: JSON-serializable expected value bounded to 16,384 encoded bytes.

[Source: python/yosoi/browser.py:348](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L348-L380)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
pointer: StrictStr
value: Any
```
