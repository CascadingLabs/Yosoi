---
title: "ResourceLimit"
description: "yosoi.outcomes.ResourceLimit Python API reference."
order: 0
---

`yosoi.outcomes.ResourceLimit`

```python
ResourceLimit = Literal['input_bytes', 'nodes', 'selector_visits', 'query_bytes', 'query_steps', 'regions', 'matches', 'captures', 'depth', 'output_bytes']
```

Locator resource classifications for byte, node, visit, query, region, match,
capture, depth, and output accounting. Each named counter has its own units.

[Source: python/yosoi/outcomes.py:41](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/outcomes.py#L41-L52)
