---
title: "Scope"
description: "yosoi.policy.Scope Python API reference."
order: 0
---

`yosoi.policy.Scope`

```python
class Scope(Model):
```

Map URL admission boundaries relative to the authored seed.

Attributes:
    hosts: seed_host or registrable_domain controls admitted hostname scope.
    paths: seed_subtree or entire_origin controls admitted URL paths. Scheme and
        port remain part of origin admission.

[Source: python/yosoi/policy.py:464](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/policy.py#L464-L474)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
hosts: HostScope = _field('map', 'scope', 'hosts')
paths: PathScope = _field('map', 'scope', 'paths')
```
