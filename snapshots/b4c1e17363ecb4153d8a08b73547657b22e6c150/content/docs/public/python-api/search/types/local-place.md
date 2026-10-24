---
title: "LocalPlace"
description: "yosoi.search.LocalPlace Python API reference."
order: 0
---

`yosoi.search.LocalPlace`

```python
class LocalPlace(ImmutableModel):
```

A provider-reported local place, without independent business verification.

Attributes:
    name: Place name displayed by the provider.
    place_url: Validated destination for the place, which has not been fetched.

[Source: python/yosoi/search.py:209](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/search.py#L209-L224)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
name: str = Field(repr=False)
place_url: SearchResultUrl = Field(repr=False)
```
