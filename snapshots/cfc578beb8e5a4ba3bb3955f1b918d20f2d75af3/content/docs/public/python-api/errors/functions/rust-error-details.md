---
title: "rust_error_details"
description: "yosoi.errors.rust_error_details Python API reference."
order: 0
---

`yosoi.errors.rust_error_details`

```python
def rust_error_details(error: BaseException) -> RustErrorDetails | None:
```

Read native Rust metadata, including through Pydantic validation errors.

Pydantic keeps its public ``ValidationError`` category and stores the
validator exception in each error context. This accessor follows those
contexts and Python's explicit cause chain to find the original native
exception without replacing the raised exception.

Args:
    error: Exception whose native details or nested validation causes to inspect.

Returns:
    The first valid native metadata record found, with recursively frozen
    mappings and sequences, or None if no such record is reachable.

[Source: python/yosoi/errors.py:74](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/errors.py#L74-L134)
