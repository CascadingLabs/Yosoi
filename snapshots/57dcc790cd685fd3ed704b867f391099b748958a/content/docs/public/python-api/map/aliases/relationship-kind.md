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

[Source: python/yosoi/map.py:360](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/map.py#L360-L360)
