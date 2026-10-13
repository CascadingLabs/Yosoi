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

[Source: python/yosoi/policy.py:585](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L585-L604)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: ProfileSelectionKind = 'current'
profile: ProviderRequestProfile | None = Field(default=None, exclude_if=lambda value: value is None)
```
