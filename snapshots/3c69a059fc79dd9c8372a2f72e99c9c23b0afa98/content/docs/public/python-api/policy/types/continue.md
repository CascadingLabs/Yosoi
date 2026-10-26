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

[Source: python/yosoi/policy.py:1058](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L1058-L1066)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['continue'] = 'continue'
```
