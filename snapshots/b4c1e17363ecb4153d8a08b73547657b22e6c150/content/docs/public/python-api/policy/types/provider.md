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

[Source: python/yosoi/policy.py:607](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L607-L624)

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

[Source: python/yosoi/policy.py:621](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L621-L624)
