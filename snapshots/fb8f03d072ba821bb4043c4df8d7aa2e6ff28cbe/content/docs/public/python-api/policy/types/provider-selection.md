---
title: "ProviderSelection"
description: "yosoi.policy.ProviderSelection Python API reference."
order: 0
---

`yosoi.policy.ProviderSelection`

```python
class ProviderSelection(Model):
```

One provider and its current or explicit child-request profile.

Attributes:
    provider: Provider occupying this authored search slot.
    profile: Current registry defaults or a complete exact request profile.

[Source: python/yosoi/policy.py:639](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L639-L694)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
provider: Provider
profile: ProfileSelection = Field(default_factory=ProfileSelection)
```

## Methods

### current

```python
@classmethod
def current(cls, provider: Provider | str) -> Self:
```

Select one provider with registry-owned defaults to resolve later.

Args:
    provider: Supported provider enum or serialized provider name.

Returns:
    Current-profile declaration; selection does not certify availability.

Raises:
    PolicyError: The provider name or declaration is unsupported.

[Source: python/yosoi/policy.py:651](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L651-L669)

### exact

```python
@classmethod
def exact(cls, provider: Provider | str, profile: ProviderRequestProfile) -> Self:
```

Select one provider with an explicit complete request profile.

Args:
    provider: Supported provider enum or serialized provider name.
    profile: Complete child-request policy sections to retain.

Returns:
    An exact-profile selection without acquiring provider results.

Raises:
    PolicyError: Provider or profile semantics are unsupported.

[Source: python/yosoi/policy.py:672](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L672-L694)
