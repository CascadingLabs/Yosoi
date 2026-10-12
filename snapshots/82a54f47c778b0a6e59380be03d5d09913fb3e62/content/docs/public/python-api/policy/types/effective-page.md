---
title: "EffectivePage"
description: "yosoi.policy.EffectivePage Python API reference."
order: 0
---

`yosoi.policy.EffectivePage`

```python
class EffectivePage(ImmutableModel):
```

Resolved acquisitions retained in authored page order.

Attributes:
    acquisitions: Concrete acquisitions and output selections for execution.

[Source: python/yosoi/policy.py:940](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L940-L947)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
acquisitions: tuple[EffectiveAcquisition, ...]
```
