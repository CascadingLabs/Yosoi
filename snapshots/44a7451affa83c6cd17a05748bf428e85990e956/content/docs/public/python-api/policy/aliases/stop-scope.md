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

[Source: python/yosoi/policy.py:1081](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L1081-L1081)
