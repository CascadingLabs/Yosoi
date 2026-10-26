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

[Source: python/yosoi/surface.py:273](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L273-L277)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['search'] = Field(default='search', description='Operation tag.')
query: StrictStr = Field(description='Literal source text, not a query language.')
```
