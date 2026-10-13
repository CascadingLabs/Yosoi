---
title: "Map"
description: "yosoi.policy.Map Python API reference."
order: 0
---

`yosoi.policy.Map`

```python
class Map(Model):
```

Complete bounded discovery declaration resolved by the Rust SDK.

Attributes:
    scope: Seed-relative host and path admission rules.
    pages: disabled or explore controls page link exploration.
    robots: ignore or respect selects applicable robots admission behavior.
    subdomains: disabled or passive selects historical name discovery.
    limits: Count, byte, concurrency, and elapsed discovery bounds.
    documents: Discard after inspection or retain within the configured document
        budget.
    filters: Explicit query-key and path-prefix exclusions.

[Source: python/yosoi/policy.py:539](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L539-L567)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
scope: Scope = _field('map', 'scope')
pages: PageDiscovery = _field('map', 'pages')
robots: Robots = _field('map', 'robots')
subdomains: Subdomains = _field('map', 'subdomains')
limits: MapLimits = _field('map', 'limits')
documents: DiscoveryDocuments = _field('map', 'documents')
filters: Filters = _field('map', 'filters')
```

## Methods

### check

```python
def check(self) -> None:
```

Validate scope, resource bounds, and exclusions without acquisition I/O.

Raises:
    PolicyError: Discovery declaration violates supported scope or bounds.

[Source: python/yosoi/policy.py:561](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L561-L567)
