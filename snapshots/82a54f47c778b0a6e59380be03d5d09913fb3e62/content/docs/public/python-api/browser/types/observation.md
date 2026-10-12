---
title: "Observation"
description: "yosoi.browser.Observation Python API reference."
order: 0
---

`yosoi.browser.Observation`

```python
class Observation(ImmutableModel):
```

Retain browser evidence from a particular document epoch.

Evidence describes an observation at capture time and does not grant live tab
authority.

Attributes:
    id: Observation identity.
    session_id: Identity of the Session that produced the observation.
    tab_id: Identity of the observed tab.
    document_epoch: Unsigned document generation used to fence stale observations.
    html: Captured HTML when this observation carries DOM evidence.
    url: Observed URL when present.
    screenshot: Optional screenshot bytes; JSON encoding uses base64.

[Source: python/yosoi/browser.py:854](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L854-L894)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
model_config = ConfigDict(ser_json_bytes='base64', val_json_bytes='base64')
id: StrictStr
session_id: StrictStr
tab_id: StrictStr
document_epoch: U64
html: StrictStr | None = None
url: StrictStr | None = None
screenshot: StrictBytes | None = None
```

## Methods

### screenshot_bytes

```python
@property
def screenshot_bytes(self) -> bytes | None:
```

Return retained screenshot bytes, or None when no image was captured.

[Source: python/yosoi/browser.py:892](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L892-L894)
