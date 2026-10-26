---
title: "SearchHitMetadata"
description: "yosoi.search.SearchHitMetadata Python API reference."
order: 0
---

`yosoi.search.SearchHitMetadata`

```python
class SearchHitMetadata(ImmutableModel):
```

Provider-displayed metadata; destination content is not fetched or verified.

Attributes:
    title: Displayed result title, absent when unavailable.
    snippet: Displayed excerpt, without verification against the destination.
    display_url: Human-readable address, which can differ from the actual
        destination.
    publisher: Displayed publisher label, without independent identity verification.
    published_at: Displayed date text, not a verified publication date.
    thumbnail_url: Validated thumbnail destination; no image fetch is implied.

[Source: python/yosoi/search.py:83](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/search.py#L83-L115)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
title: str | None = Field(default=None, repr=False)
snippet: str | None = Field(default=None, repr=False)
display_url: str | None = Field(default=None, repr=False)
publisher: str | None = Field(default=None, repr=False)
published_at: str | None = Field(default=None, repr=False)
thumbnail_url: SearchResultUrl | None = Field(default=None, repr=False)
```
