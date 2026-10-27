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

[Source: python/yosoi/policy.py:84](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/policy.py#L84-L84)
