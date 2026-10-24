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

[Source: python/yosoi/policy.py:72](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L72-L72)
