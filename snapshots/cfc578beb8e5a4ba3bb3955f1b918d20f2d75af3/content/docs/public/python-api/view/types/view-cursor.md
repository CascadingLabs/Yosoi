---
title: "ViewCursor"
description: "yosoi.view.ViewCursor Python API reference."
order: 0
---

`yosoi.view.ViewCursor`

```python
class ViewCursor(ImmutableModel):
```

Continuation position that Rust validates against the original capture.

Attributes:
    capture: Binding to exact observation provenance and retained HTML.
    offset: Next element offset, checked by Rust on continuation.
    page_size: Requested row bound, at most 100.

[Source: python/yosoi/view.py:48](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/view.py#L48-L59)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
capture: ViewCaptureToken
offset: int = Field(strict=True, ge=0, le=2 ** 64 - 1)
page_size: int = Field(strict=True, ge=1, le=100)
```
