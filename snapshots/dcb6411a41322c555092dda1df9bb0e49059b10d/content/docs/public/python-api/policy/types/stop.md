---
title: "Stop"
description: "yosoi.policy.Stop Python API reference."
order: 0
---

`yosoi.policy.Stop`

```python
class Stop(ImmutableModel):
```

Stop a selected Flow scope after failure or cancellation.

Attributes:
    kind: Discriminator fixed to stop.
    scope: current_flow omits its remaining leaves; invocation stops the entire
        invocation.

[Source: python/yosoi/policy.py:1087](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L1087-L1097)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['stop'] = 'stop'
scope: StopScope
```
