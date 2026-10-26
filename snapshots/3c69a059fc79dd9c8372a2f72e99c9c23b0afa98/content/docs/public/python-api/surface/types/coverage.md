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

[Source: python/yosoi/surface.py:110](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L110-L118)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
complete: StrictBool = Field(description='Whether this representation covers its source.')
reason: StrictStr | None = Field(default=None, description='Reason coverage is partial.')
```
