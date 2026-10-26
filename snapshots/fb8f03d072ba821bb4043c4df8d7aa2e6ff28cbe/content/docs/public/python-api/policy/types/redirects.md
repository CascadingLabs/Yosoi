---
title: "Redirects"
description: "yosoi.policy.Redirects Python API reference."
order: 0
---

`yosoi.policy.Redirects`

```python
class Redirects(Model):
```

Direct HTTP redirect traversal configuration.

Attributes:
    kind: disabled for no traversal; follow requires both hop and target settings.
    max_hops: Positive redirect-transition count when following, otherwise None.
    targets: HTTP(S) targets or same-origin restriction when following, otherwise
        None.

[Source: python/yosoi/policy.py:366](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L366-L395)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['disabled', 'follow']
max_hops: RedirectHopLimitValue | None = None
targets: DirectHttpRedirectTargets | None = None
```

## Methods

### default

```python
@classmethod
def default(cls) -> Self:
```

Return redirect behavior selected by the current Rust package default.

[Source: python/yosoi/policy.py:381](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L381-L385)
