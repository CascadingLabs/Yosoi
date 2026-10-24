---
title: "DiscoverySource"
description: "yosoi.map.DiscoverySource Python API reference."
order: 0
---

`yosoi.map.DiscoverySource`

```python
class DiscoverySource(_MapOrderable):
```

Provenance category for a retained hostname or page.

Attributes:
    kind: seed is caller input; html_link and xml_link are acquired links; sitemap
        and robots are support sources; redirect is observed HTTP routing;
        passive_provider and passive_certificate are historical evidence.
    value: Index provider for passive_provider, otherwise None.

[Source: python/yosoi/map.py:231](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/map.py#L231-L258)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['seed', 'html_link', 'xml_link', 'passive_provider', 'sitemap', 'robots', 'redirect', 'passive_certificate']
value: PublicProvider | None = None
```

## Methods

### is_passive

```python
@property
def is_passive(self) -> bool:
```

Return whether provenance is passive index or certificate evidence.

[Source: python/yosoi/map.py:256](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/map.py#L256-L258)
