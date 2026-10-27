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

[Source: python/yosoi/surface.py:117](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L117-L125)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
complete: StrictBool = Field(description='Whether this representation covers its source.')
reason: StrictStr | None = Field(default=None, description='Reason coverage is partial.')
```
