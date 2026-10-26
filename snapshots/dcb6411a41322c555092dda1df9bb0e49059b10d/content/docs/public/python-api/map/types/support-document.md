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

[Source: python/yosoi/map.py:435](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/map.py#L435-L446)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
url: str
kind: Literal['robots', 'sitemap', 'sitemap_index']
status: SourceStatus
```
