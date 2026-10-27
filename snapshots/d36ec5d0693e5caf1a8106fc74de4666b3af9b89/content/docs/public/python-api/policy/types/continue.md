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

[Source: python/yosoi/policy.py:1070](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/policy.py#L1070-L1078)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['continue'] = 'continue'
```
