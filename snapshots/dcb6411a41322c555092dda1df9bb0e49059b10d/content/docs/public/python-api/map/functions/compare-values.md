---
title: "compare_values"
description: "yosoi.map.compare_values Python API reference."
order: 0
---

`yosoi.map.compare_values`

```python
def compare_values(kind: MapOrderingKind, left: object, right: object) -> int:
```

Compare typed Map values with the public Rust `Ord` implementation.

String-backed Literal aliases remain ordinary strings; pass their kind to
this function when their Rust enum declaration order is needed.

[Source: python/yosoi/map.py:45](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/map.py#L45-L63)
