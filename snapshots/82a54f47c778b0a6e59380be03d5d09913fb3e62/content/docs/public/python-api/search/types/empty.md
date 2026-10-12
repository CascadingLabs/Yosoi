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

[Source: python/yosoi/search.py:394](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/search.py#L394-L401)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['empty']
```
