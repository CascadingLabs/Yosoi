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

[Source: python/yosoi/policy.py:1069](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L1069-L1069)
