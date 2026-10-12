---
title: "OmissionReason"
description: "yosoi.map.OmissionReason Python API reference."
order: 0
---

`yosoi.map.OmissionReason`

```python
class OmissionReason(_MapOrderable):
```

Classification of omitted discovery evidence or exploration work.

Attributes:
    kind: admission, robots, depth, sitemap_depth, pending, inventory, retention,
        wildcard, or other explains the rejection or boundary. Wildcards remain
        patterns rather than expanded concrete hosts.
    value: URL or hostname rejection details for admission, otherwise None.

[Source: python/yosoi/map.py:510](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/map.py#L510-L533)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['admission', 'robots', 'depth', 'sitemap_depth', 'pending', 'inventory', 'retention', 'wildcard', 'other']
value: Rejection | None = None
```
