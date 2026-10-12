---
title: "RustErrorDetails"
description: "yosoi.errors.RustErrorDetails Python API reference."
order: 0
---

`yosoi.errors.RustErrorDetails`

```python
class RustErrorDetails:
```

Exact Rust error identity and structured payload attached by the binding.

Values returned by rust_error_details contain recursively frozen payloads.
The dataclass prevents attribute reassignment; constructing it directly does
not freeze a caller-supplied mapping.

Attributes:
    rust_type: Rust type name recorded by the native binding.
    variant: Public enum variant name, or None for an opaque error wrapper.
    details: Structured variant payload, without replacing the exception.
    source_chain: Display messages from nested Rust source errors, in order.

[Source: python/yosoi/errors.py:43](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/errors.py#L43-L60)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
rust_type: str
variant: str | None
details: Mapping[str, Any]
source_chain: tuple[str, ...] = ()
```
