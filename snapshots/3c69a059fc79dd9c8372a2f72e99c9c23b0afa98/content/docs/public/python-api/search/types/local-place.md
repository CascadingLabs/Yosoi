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

[Source: python/yosoi/search.py:209](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/search.py#L209-L224)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
name: str = Field(repr=False)
place_url: SearchResultUrl = Field(repr=False)
```
