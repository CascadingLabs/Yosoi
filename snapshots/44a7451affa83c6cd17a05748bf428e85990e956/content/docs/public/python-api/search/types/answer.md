---
title: "Answer"
description: "yosoi.search.Answer Python API reference."
order: 0
---

`yosoi.search.Answer`

```python
class Answer(ImmutableModel):
```

A provider-displayed answer with reported citation destinations.

Attributes:
    kind: Discriminator fixed to answer for tagged decoding.
    placement_index: One-based position among provider-page placements.
    text: Displayed answer text, without factual verification.
    citations: Validated citation destinations; their contents have not been
        fetched.

[Source: python/yosoi/search.py:249](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/search.py#L249-L272)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['answer']
placement_index: Rank
text: str = Field(repr=False)
citations: tuple[SearchResultUrl, ...] = Field(repr=False)
```
