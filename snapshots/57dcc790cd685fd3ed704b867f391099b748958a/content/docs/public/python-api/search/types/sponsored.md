---
title: "Sponsored"
description: "yosoi.search.Sponsored Python API reference."
order: 0
---

`yosoi.search.Sponsored`

```python
class Sponsored(ImmutableModel):
```

A provider placement identified as sponsored content, without an organic rank.

Attributes:
    kind: Discriminator fixed to sponsored for tagged decoding.
    placement_index: One-based position among provider-page placements.
    destination: Validated HTTP(S) destination, without a subsequent fetch.
    label: Provider-displayed sponsorship label, or None when unavailable.

[Source: python/yosoi/search.py:227](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/search.py#L227-L246)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['sponsored']
placement_index: Rank
destination: SearchResultUrl = Field(repr=False)
label: str | None = Field(repr=False)
```
