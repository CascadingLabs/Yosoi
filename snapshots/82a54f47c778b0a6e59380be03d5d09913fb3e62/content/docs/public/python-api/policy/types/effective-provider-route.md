---
title: "EffectiveProviderRoute"
description: "yosoi.policy.EffectiveProviderRoute Python API reference."
order: 0
---

`yosoi.policy.EffectiveProviderRoute`

```python
class EffectiveProviderRoute(ImmutableModel):
```

Resolved provider profile with its default-selection provenance.

Attributes:
    provider: Provider occupying the authored search slot.
    profile: Resolved child profile, absent when unavailable.
    profile_selection_kind: Current defaults or an exact authored declaration.
    defaults_status: Certification/availability or exact-profile provenance.

[Source: python/yosoi/policy.py:979](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L979-L1032)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
provider: Provider
profile: ProviderRequestProfile | None
profile_selection_kind: Literal['current', 'exact']
defaults_status: ProviderDefaultsStatus
```

## Methods

### page

```python
@property
def page(self) -> Page | None:
```

Return acquisition/output settings, or None when unavailable.

[Source: python/yosoi/policy.py:995](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L995-L1002)

### request

```python
@property
def request(self) -> Request | None:
```

Return timing/evidence settings, or None when unavailable.

[Source: python/yosoi/policy.py:1005](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L1005-L1012)

### documents

```python
@property
def documents(self) -> Documents | None:
```

Return a retained-document parsing profile copy, or None when unavailable.

[Source: python/yosoi/policy.py:1015](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L1015-L1022)

### defaults_version

```python
@property
def defaults_version(self) -> ProviderDefaultsVersion | None:
```

Return the defaults version, absent for exact or unavailable profiles.

[Source: python/yosoi/policy.py:1025](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L1025-L1032)
