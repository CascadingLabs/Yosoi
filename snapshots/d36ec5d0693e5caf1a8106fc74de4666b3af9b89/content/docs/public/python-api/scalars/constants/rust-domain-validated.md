---
title: "RUST_DOMAIN_VALIDATED"
description: "yosoi.scalars.RUST_DOMAIN_VALIDATED Python API reference."
order: 0
---

`yosoi.scalars.RUST_DOMAIN_VALIDATED`

```python
RUST_DOMAIN_VALIDATED = object()
```

Internal reconstruction context for data already checked by Rust.

Pydantic domain validators use this marker to avoid repeating native checks.
It does not validate caller input or create ownership of native resources.

[Source: python/yosoi/scalars.py:12](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/scalars.py#L12-L12)
