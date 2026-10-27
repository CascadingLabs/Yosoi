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

[Source: python/yosoi/policy.py:1087](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/policy.py#L1087-L1097)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['stop'] = 'stop'
scope: StopScope
```
