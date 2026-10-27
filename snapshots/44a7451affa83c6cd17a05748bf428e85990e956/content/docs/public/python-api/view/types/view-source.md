---
title: "ViewSource"
description: "yosoi.view.ViewSource Python API reference."
order: 0
---

`yosoi.view.ViewSource`

```python
class ViewSource(ImmutableModel):
```

Provenance of retained evidence, without browser control authority.

Attributes:
    observation_id: Immutable captured observation identity.
    session_id: Recorded browser Session identity.
    tab_id: Recorded tab identity.
    document_epoch: Positive captured document generation.
    url: Optional observed source URL, never fetched by View.

[Source: python/yosoi/view.py:18](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/view.py#L18-L33)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
observation_id: StrictStr
session_id: StrictStr
tab_id: StrictStr
document_epoch: int = Field(strict=True, ge=1, le=2 ** 64 - 1)
url: StrictStr | None = None
```
