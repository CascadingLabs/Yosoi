---
title: "ProfileSelection"
description: "yosoi.policy.ProfileSelection Python API reference."
order: 0
---

`yosoi.policy.ProfileSelection`

```python
class ProfileSelection(Model):
```

Current provider defaults or an explicit complete request profile.

Attributes:
    kind: current resolves package registry metadata; exact retains an authored
        profile.
    profile: None for current selection, required complete profile for exact
        selection.

[Source: python/yosoi/policy.py:597](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L597-L616)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: ProfileSelectionKind = 'current'
profile: ProviderRequestProfile | None = Field(default=None, exclude_if=lambda value: value is None)
```
