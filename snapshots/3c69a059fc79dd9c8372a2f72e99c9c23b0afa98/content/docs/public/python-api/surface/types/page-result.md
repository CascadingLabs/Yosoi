---
title: "PageResult"
description: "yosoi.surface.PageResult Python API reference."
order: 0
---

`yosoi.surface.PageResult`

```python
class PageResult(ImmutableModel):
```

Tagged shared routing result.

[Source: python/yosoi/surface.py:342](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L342-L346)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['page'] = Field(default='page', description='Result tag.')
data: Page = Field(description='Bounded routing window.')
```
