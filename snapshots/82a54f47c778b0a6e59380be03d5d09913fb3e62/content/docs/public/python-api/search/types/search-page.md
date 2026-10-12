---
title: "SearchPage"
description: "yosoi.search.SearchPage Python API reference."
order: 0
---

`yosoi.search.SearchPage`

```python
class SearchPage(ImmutableModel):
```

Normalized content extracted from one provider response.

Attributes:
    hits: Accepted organic results in provider order; ranks can contain gaps.
    features: Supported rich placements, independent of organic ranks.
    coverage: Independent organic and rich-feature extraction coverage claims.
    issues: Retained nonfatal issues; configured budgets can bound their count.

[Source: python/yosoi/search.py:354](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/search.py#L354-L379)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
hits: tuple[SearchHit, ...] = Field(repr=False)
features: tuple[SearchFeature, ...] = Field(repr=False)
coverage: SearchCoverage
issues: tuple[SearchIssue, ...] = Field(repr=False)
```
