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

[Source: python/yosoi/policy.py:1069](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L1069-L1069)
