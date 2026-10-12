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

[Source: python/yosoi/policy.py:354](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L354-L383)

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

[Source: python/yosoi/policy.py:369](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L369-L373)
