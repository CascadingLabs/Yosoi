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

[Source: python/yosoi/locators.py:72](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/locators.py#L72-L81)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
prefix: str
namespace_uri: str
```
