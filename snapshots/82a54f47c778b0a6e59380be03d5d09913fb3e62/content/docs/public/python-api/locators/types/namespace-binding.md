---
title: "NamespaceBinding"
description: "yosoi.locators.NamespaceBinding Python API reference."
order: 0
---

`yosoi.locators.NamespaceBinding`

```python
class NamespaceBinding(ImmutableModel):
```

Query-local XML namespace binding independent of source prefixes.

Attributes:
    prefix: Authored query prefix; empty denotes a default namespace binding.
    namespace_uri: Nonblank namespace URI used to identify expanded XML names.

[Source: python/yosoi/locators.py:72](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/locators.py#L72-L81)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
prefix: str
namespace_uri: str
```
