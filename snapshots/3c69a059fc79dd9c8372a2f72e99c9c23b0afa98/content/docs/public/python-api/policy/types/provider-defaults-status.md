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

[Source: python/yosoi/policy.py:950](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L950-L976)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['unavailable', 'preview', 'certified', 'exact']
registry_version: U16 | None = None
version: ProviderDefaultsVersion | None = None
```
