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

[Source: python/yosoi/browser.py:345](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L345-L377)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
pointer: StrictStr
value: Any
```
