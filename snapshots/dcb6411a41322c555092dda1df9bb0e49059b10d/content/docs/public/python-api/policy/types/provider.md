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

[Source: python/yosoi/policy.py:619](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L619-L636)

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

[Source: python/yosoi/policy.py:633](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L633-L636)
