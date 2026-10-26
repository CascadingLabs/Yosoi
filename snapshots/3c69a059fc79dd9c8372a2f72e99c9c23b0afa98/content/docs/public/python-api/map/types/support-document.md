---
title: "SupportDocument"
description: "yosoi.map.SupportDocument Python API reference."
order: 0
---

`yosoi.map.SupportDocument`

```python
class SupportDocument(ImmutableModel):
```

A robots or sitemap support source and its execution state.

Attributes:
    url: Normalized support-document URL.
    kind: robots for rules; sitemap for page URLs; sitemap_index for nested sources.
    status: Processing state, including failures and incomplete evidence.

[Source: python/yosoi/map.py:435](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/map.py#L435-L446)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
url: str
kind: Literal['robots', 'sitemap', 'sitemap_index']
status: SourceStatus
```
