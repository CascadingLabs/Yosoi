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

[Source: python/yosoi/outcomes.py:41](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/outcomes.py#L41-L52)
