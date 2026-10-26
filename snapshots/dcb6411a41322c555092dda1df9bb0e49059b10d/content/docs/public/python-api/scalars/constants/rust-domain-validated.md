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

[Source: python/yosoi/scalars.py:12](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/scalars.py#L12-L12)
