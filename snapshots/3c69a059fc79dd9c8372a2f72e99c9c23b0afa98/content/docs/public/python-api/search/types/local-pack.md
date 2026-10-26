---
title: "LocalPack"
description: "yosoi.search.LocalPack Python API reference."
order: 0
---

`yosoi.search.LocalPack`

```python
class LocalPack(ImmutableModel):
```

A provider-displayed collection of local places and an optional map.

Attributes:
    kind: Discriminator fixed to local_pack for tagged decoding.
    placement_index: One-based position of the pack among provider-page placements.
    places: Provider-reported places, without independent business verification.
    map_url: Validated map destination, or None when unavailable.

[Source: python/yosoi/search.py:299](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/search.py#L299-L321)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['local_pack']
placement_index: Rank
places: tuple[LocalPlace, ...] = Field(repr=False)
map_url: SearchResultUrl | None = Field(repr=False)
```
