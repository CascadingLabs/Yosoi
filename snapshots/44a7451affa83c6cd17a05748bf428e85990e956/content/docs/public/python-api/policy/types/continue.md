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

[Source: python/yosoi/policy.py:1070](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L1070-L1078)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['continue'] = 'continue'
```
