---
title: "SearchCoverage"
description: "yosoi.search.SearchCoverage Python API reference."
order: 0
---

`yosoi.search.SearchCoverage`

```python
class SearchCoverage(ImmutableModel):
```

Independent extraction coverage for organic results and rich features.

Attributes:
    web: complete means supported extraction finished; partial means evidence was
        omitted or query recovery was used. Neither proves exhaustive web search.
    rich_features: not_collected means extraction was not attempted; collected can
        include an empty result; partial records incomplete feature evidence.

[Source: python/yosoi/search.py:177](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/search.py#L177-L188)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
web: Literal['complete', 'partial']
rich_features: Literal['not_collected', 'collected', 'partial']
```
