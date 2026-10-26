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

[Source: python/yosoi/policy.py:1075](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L1075-L1085)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['stop'] = 'stop'
scope: StopScope
```
