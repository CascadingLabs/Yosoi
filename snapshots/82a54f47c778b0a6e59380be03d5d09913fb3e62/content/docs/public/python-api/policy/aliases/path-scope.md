---
title: "PathScope"
description: "yosoi.policy.PathScope Python API reference."
order: 0
---

`yosoi.policy.PathScope`

```python
PathScope = Literal['seed_subtree', 'entire_origin']
```

Map admission stays within the seed path subtree or admits the entire origin;
scheme, port, and host rules remain independent.

[Source: python/yosoi/policy.py:72](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L72-L72)
