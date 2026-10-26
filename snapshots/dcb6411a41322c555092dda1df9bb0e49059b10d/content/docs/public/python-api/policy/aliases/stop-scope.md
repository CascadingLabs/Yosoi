---
title: "StopScope"
description: "yosoi.policy.StopScope Python API reference."
order: 0
---

`yosoi.policy.StopScope`

```python
StopScope = Literal['current_flow', 'invocation']
```

current_flow stops its remaining leaves; invocation stops all remaining invocation
work. Unknown effects can still force a hard safety stop.

[Source: python/yosoi/policy.py:1081](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L1081-L1081)
