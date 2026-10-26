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

[Source: python/yosoi/policy.py:991](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L991-L1044)

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

[Source: python/yosoi/policy.py:1007](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L1007-L1014)

### request

```python
@property
def request(self) -> Request | None:
```

Return timing/evidence settings, or None when unavailable.

[Source: python/yosoi/policy.py:1017](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L1017-L1024)

### documents

```python
@property
def documents(self) -> Documents | None:
```

Return a retained-document parsing profile copy, or None when unavailable.

[Source: python/yosoi/policy.py:1027](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L1027-L1034)

### defaults_version

```python
@property
def defaults_version(self) -> ProviderDefaultsVersion | None:
```

Return the defaults version, absent for exact or unavailable profiles.

[Source: python/yosoi/policy.py:1037](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L1037-L1044)
