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

[Source: python/yosoi/policy.py:529](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L529-L548)

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

[Source: python/yosoi/policy.py:542](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L542-L548)
