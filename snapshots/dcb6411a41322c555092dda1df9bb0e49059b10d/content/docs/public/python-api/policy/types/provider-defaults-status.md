---
title: "ProviderDefaultsStatus"
description: "yosoi.policy.ProviderDefaultsStatus Python API reference."
order: 0
---

`yosoi.policy.ProviderDefaultsStatus`

```python
class ProviderDefaultsStatus(ImmutableModel):
```

Explicit registry certification or exact-profile provenance.

Attributes:
    status: unavailable, preview, certified, or exact distinguishes default
        eligibility from authored profiles.
    registry_version: Registry version when defaults are unavailable, otherwise
        None.
    version: Positive defaults-profile version for preview/certified metadata,
        otherwise None.

[Source: python/yosoi/policy.py:962](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L962-L988)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['unavailable', 'preview', 'certified', 'exact']
registry_version: U16 | None = None
version: ProviderDefaultsVersion | None = None
```
