---
title: "SearchHit"
description: "yosoi.search.SearchHit Python API reference."
order: 0
---

`yosoi.search.SearchHit`

```python
class SearchHit(ImmutableModel):
```

An accepted organic result in provider order, with possible rank gaps.

Attributes:
    url: Validated HTTP(S) destination for an explicit later request.
    organic_rank: One-based organic row rank; rejected or duplicate rows can leave
        gaps.
    placement_index: One-based placement on the provider page, including rich
        features.
    metadata: Optional provider-displayed details, without a destination fetch.

[Source: python/yosoi/search.py:118](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/search.py#L118-L174)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
url: SearchResultUrl = Field(repr=False)
organic_rank: Rank
placement_index: Rank
metadata: SearchHitMetadata = Field(repr=False)
```

## Methods

### title

```python
@property
def title(self) -> str | None:
```

Return the provider-displayed title, or None when unavailable.

[Source: python/yosoi/search.py:147](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/search.py#L147-L149)

### snippet

```python
@property
def snippet(self) -> str | None:
```

Return the provider excerpt without fetching or verifying the destination.

[Source: python/yosoi/search.py:152](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/search.py#L152-L154)

### display_url

```python
@property
def display_url(self) -> str | None:
```

Return the displayed address, which can differ from the destination.

[Source: python/yosoi/search.py:157](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/search.py#L157-L159)

### publisher

```python
@property
def publisher(self) -> str | None:
```

Return the unverified provider-displayed publisher label.

[Source: python/yosoi/search.py:162](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/search.py#L162-L164)

### published_at

```python
@property
def published_at(self) -> str | None:
```

Return displayed date text, not a verified publication date.

[Source: python/yosoi/search.py:167](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/search.py#L167-L169)

### thumbnail_url

```python
@property
def thumbnail_url(self) -> str | None:
```

Return the validated thumbnail destination, without fetching an image.

[Source: python/yosoi/search.py:172](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/search.py#L172-L174)
