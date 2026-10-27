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

[Source: python/yosoi/map.py:360](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/map.py#L360-L360)
