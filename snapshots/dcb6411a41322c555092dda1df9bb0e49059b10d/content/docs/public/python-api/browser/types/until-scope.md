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
    protocol: Coordinate protocol; omitted legacy reports use CDP.
    frame_id: Optional frame identity; required for a satisfied report.
    loader_id: Document loader identity, required for CDP success and absent
        for BiDi.

[Source: python/yosoi/browser.py:1025](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L1025-L1056)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
session_id: StrictStr = Field(min_length=1, max_length=4096)
tab_id: StrictStr = Field(min_length=1, max_length=4096)
document_epoch: U64
protocol: Literal['cdp', 'bidi'] | None = Field(default=None, exclude_if=lambda value: value is None, description='Coordinate protocol; omitted legacy reports use CDP.')
frame_id: StrictStr | None = Field(default=None, min_length=1, max_length=4096)
loader_id: StrictStr | None = Field(default=None, min_length=1, max_length=4096)
```
