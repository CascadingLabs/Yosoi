---
title: "RelationshipKind"
description: "yosoi.map.RelationshipKind Python API reference."
order: 0
---

`yosoi.map.RelationshipKind`

```python
RelationshipKind = Literal['link', 'redirect', 'canonical']
```

Directed link, redirect, or canonical-hint evidence. Links add rooted depth,
redirects preserve depth, and canonical hints do not create traversal parents.

[Source: python/yosoi/map.py:360](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/map.py#L360-L360)
