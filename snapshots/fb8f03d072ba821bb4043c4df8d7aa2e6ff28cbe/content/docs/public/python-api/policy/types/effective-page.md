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

[Source: python/yosoi/policy.py:952](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L952-L959)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
acquisitions: tuple[EffectiveAcquisition, ...]
```
