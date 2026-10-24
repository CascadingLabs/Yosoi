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

[Source: python/yosoi/policy.py:940](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L940-L947)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
acquisitions: tuple[EffectiveAcquisition, ...]
```
