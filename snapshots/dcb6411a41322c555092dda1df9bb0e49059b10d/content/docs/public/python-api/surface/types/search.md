---
title: "Search"
description: "yosoi.surface.Search Python API reference."
order: 0
---

`yosoi.surface.Search`

```python
class Search(ImmutableModel):
```

Request literal search when advertised by this representation.

[Source: python/yosoi/surface.py:280](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L280-L284)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['search'] = Field(default='search', description='Operation tag.')
query: StrictStr = Field(description='Literal source text, not a query language.')
```
