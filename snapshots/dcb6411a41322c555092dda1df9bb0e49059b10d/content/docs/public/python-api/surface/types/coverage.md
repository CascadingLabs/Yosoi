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

[Source: python/yosoi/surface.py:117](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L117-L125)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
complete: StrictBool = Field(description='Whether this representation covers its source.')
reason: StrictStr | None = Field(default=None, description='Reason coverage is partial.')
```
