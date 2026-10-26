---
title: "Coverage"
description: "yosoi.surface.Coverage Python API reference."
order: 0
---

`yosoi.surface.Coverage`

```python
class Coverage(ImmutableModel):
```

Source completeness, independent of how many entries fit on a page.

[Source: python/yosoi/surface.py:117](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L117-L125)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
complete: StrictBool = Field(description='Whether this representation covers its source.')
reason: StrictStr | None = Field(default=None, description='Reason coverage is partial.')
```
