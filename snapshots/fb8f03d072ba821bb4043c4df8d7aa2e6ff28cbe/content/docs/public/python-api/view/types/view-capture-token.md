---
title: "ViewCaptureToken"
description: "yosoi.view.ViewCaptureToken Python API reference."
order: 0
---

`yosoi.view.ViewCaptureToken`

```python
class ViewCaptureToken(ImmutableModel):
```

Capture binding retained by each View and continuation cursor.

Attributes:
    source: Exact captured provenance.
    fingerprint: Advisory HTML fingerprint, not a cryptographic integrity digest.

[Source: python/yosoi/view.py:36](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/view.py#L36-L45)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
source: ViewSource
fingerprint: int = Field(strict=True, ge=0, le=2 ** 64 - 1)
```
