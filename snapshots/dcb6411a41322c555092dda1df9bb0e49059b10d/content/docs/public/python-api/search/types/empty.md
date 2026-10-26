---
title: "Empty"
description: "yosoi.search.Empty Python API reference."
order: 0
---

`yosoi.search.Empty`

```python
class Empty(ImmutableModel):
```

A parsed provider response with no accepted results.

Attributes:
    status: Discriminator fixed to empty for tagged decoding.

[Source: python/yosoi/search.py:394](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/search.py#L394-L401)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['empty']
```
