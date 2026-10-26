---
title: "Continue"
description: "yosoi.policy.Continue Python API reference."
order: 0
---

`yosoi.policy.Continue`

```python
class Continue(ImmutableModel):
```

Retain an unsuccessful result and attempt the next safe step.

Attributes:
    kind: Discriminator fixed to continue. Unknown effects or unsafe state can still
        force a hard stop.

[Source: python/yosoi/policy.py:1070](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L1070-L1078)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['continue'] = 'continue'
```
