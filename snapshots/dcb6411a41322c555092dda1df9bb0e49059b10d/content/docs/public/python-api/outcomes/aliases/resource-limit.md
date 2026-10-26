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

[Source: python/yosoi/outcomes.py:41](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/outcomes.py#L41-L52)
