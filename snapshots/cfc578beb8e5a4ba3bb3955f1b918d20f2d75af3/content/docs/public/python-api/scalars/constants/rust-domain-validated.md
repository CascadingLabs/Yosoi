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

[Source: python/yosoi/scalars.py:12](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/scalars.py#L12-L12)
