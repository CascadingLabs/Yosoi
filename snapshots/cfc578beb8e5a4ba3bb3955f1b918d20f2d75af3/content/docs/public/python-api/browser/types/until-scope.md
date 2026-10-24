---
title: "UntilScope"
description: "yosoi.browser.UntilScope Python API reference."
order: 0
---

`yosoi.browser.UntilScope`

```python
class UntilScope(ImmutableModel):
```

Fence an Until report to its Session, tab, and document.

Attributes:
    session_id: Owning Session identity.
    tab_id: Observed tab identity.
    document_epoch: Document generation evaluated by the wait.
    frame_id: Optional frame identity; required for a satisfied report.
    loader_id: Optional document loader identity; required for a satisfied report.

[Source: python/yosoi/browser.py:936](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L936-L960)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
session_id: StrictStr = Field(min_length=1, max_length=4096)
tab_id: StrictStr = Field(min_length=1, max_length=4096)
document_epoch: U64
frame_id: StrictStr | None = Field(default=None, min_length=1, max_length=4096)
loader_id: StrictStr | None = Field(default=None, min_length=1, max_length=4096)
```
