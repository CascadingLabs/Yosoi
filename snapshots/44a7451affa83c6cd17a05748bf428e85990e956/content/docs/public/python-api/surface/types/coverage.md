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

[Source: python/yosoi/surface.py:117](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L117-L125)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
complete: StrictBool = Field(description='Whether this representation covers its source.')
reason: StrictStr | None = Field(default=None, description='Reason coverage is partial.')
```
