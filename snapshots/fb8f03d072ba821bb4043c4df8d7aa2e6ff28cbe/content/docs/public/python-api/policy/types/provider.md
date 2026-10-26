---
title: "Provider"
description: "yosoi.policy.Provider Python API reference."
order: 0
---

`yosoi.policy.Provider`

```python
class Provider(StrEnum):
```

Supported provider names with Rust registry default-status evidence.

Attributes:
    brave: Brave public search route.
    bing: Bing public search route.
    duck_duck_go: DuckDuckGo public search route. Selection does not guarantee
        availability or certification.

[Source: python/yosoi/policy.py:619](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L619-L636)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
brave = 'brave'
bing = 'bing'
duck_duck_go = 'duck_duck_go'
```

## Methods

### defaults_status

```python
def defaults_status(self) -> ProviderDefaultsStatus:
```

Return registry availability/certification without executing a search.

[Source: python/yosoi/policy.py:633](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L633-L636)
