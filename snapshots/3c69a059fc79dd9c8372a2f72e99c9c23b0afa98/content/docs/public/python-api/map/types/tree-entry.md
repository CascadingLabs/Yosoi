---
title: "TreeEntry"
description: "yosoi.map.TreeEntry Python API reference."
order: 0
---

`yosoi.map.TreeEntry`

```python
class TreeEntry(ImmutableModel):
```

A page position in the deterministic rooted discovery forest.

Attributes:
    page: Normalized inventoried page URL.
    parent: Selected rooted predecessor, or None for roots and unattached pages.
    depth: Established link depth; redirects do not increase it, and None means no
        rooted path was found.

[Source: python/yosoi/map.py:449](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/map.py#L449-L461)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
page: str
parent: str | None
depth: int | None
```
