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

[Source: python/yosoi/policy.py:1075](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L1075-L1085)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['stop'] = 'stop'
scope: StopScope
```
