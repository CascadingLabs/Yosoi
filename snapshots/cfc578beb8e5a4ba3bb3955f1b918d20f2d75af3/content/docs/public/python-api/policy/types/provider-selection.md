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

[Source: python/yosoi/policy.py:627](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L627-L682)

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

[Source: python/yosoi/policy.py:639](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L639-L657)

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

[Source: python/yosoi/policy.py:660](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L660-L682)
