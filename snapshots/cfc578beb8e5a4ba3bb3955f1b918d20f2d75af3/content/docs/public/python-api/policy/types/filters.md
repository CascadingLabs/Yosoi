---
title: "Filters"
description: "yosoi.policy.Filters Python API reference."
order: 0
---

`yosoi.policy.Filters`

```python
class Filters(Model):
```

Explicit Map admission exclusions rather than discovery selectors.

Attributes:
    excluded_query_keys: URL query key names to exclude during admission.
    excluded_path_prefixes: Literal URL path prefixes to exclude.

[Source: python/yosoi/policy.py:517](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L517-L536)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
excluded_query_keys: list[str] = _field('map', 'filters', 'excluded_query_keys')
excluded_path_prefixes: list[str] = _field('map', 'filters', 'excluded_path_prefixes')
```

## Methods

### check

```python
def check(self) -> None:
```

Validate admission exclusions in Rust without discovering URLs.

Raises:
    PolicyError: Exclusion declarations exceed supported shape or bounds.

[Source: python/yosoi/policy.py:530](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L530-L536)
