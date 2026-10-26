---
title: "Relationship"
description: "yosoi.map.Relationship Python API reference."
order: 0
---

`yosoi.map.Relationship`

```python
class Relationship(_MapOrderable):
```

Directed discovery evidence without merging the endpoint pages.

Attributes:
    from_url: Reporting page URL; serialized under the Rust field name from.
    to: Admitted normalized destination URL.
    kind: link increases rooted depth; redirect preserves it; canonical is a hint
        and does not establish a tree parent.

[Source: python/yosoi/map.py:366](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/map.py#L366-L380)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
from_url: str = Field(alias='from')
to: str
kind: RelationshipKind
```
