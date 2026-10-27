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

[Source: python/yosoi/surface.py:349](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L349-L353)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['page'] = Field(default='page', description='Result tag.')
data: Page = Field(description='Bounded routing window.')
```
