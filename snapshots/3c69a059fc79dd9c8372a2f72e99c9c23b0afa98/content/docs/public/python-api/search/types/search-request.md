---
title: "SearchRequest"
description: "yosoi.search.SearchRequest Python API reference."
order: 0
---

`yosoi.search.SearchRequest`

```python
class SearchRequest(NativeAuthoringModel):
```

Authored query intent backed by Rust, independent of provider selection.

Attributes:
    query: Original nonblank query of at most 512 UTF-8 bytes. Constructing the
        request validates it without provider I/O.

[Source: python/yosoi/search.py:626](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/search.py#L626-L685)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
query: str = Field(repr=False)
```

## Methods

### model_post_init

```python
def model_post_init(self, context: object) -> None:
```

Validate the query in Rust and initialize its immutable native handle.

[Source: python/yosoi/search.py:637](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/search.py#L637-L639)

### id

```python
@property
def id(self) -> str:
```

Return the retained query identity shared by bindings and sends.

[Source: python/yosoi/search.py:642](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/search.py#L642-L644)

### bind

```python
def bind(self, policy: Policy) -> BoundSearchRequest:
```

Bind this request to a snapshot of the supplied policy without provider I/O.

Args:
    policy: Complete policy declaration to serialize at binding time.

Returns:
    A binding unaffected by later edits to the caller policy.

[Source: python/yosoi/search.py:646](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/search.py#L646-L655)

### check

```python
def check(self) -> None:
```

Validate against package defaults without sending provider requests.

Raises:
    SearchError: Provider selection, policy resolution, or execution setup is
        invalid.

[Source: python/yosoi/search.py:657](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/search.py#L657-L664)

### send

```python
async def send(self, *, cancellation: CancellationToken | None=None) -> SearchResponse:
```

Run selected providers with package defaults and retain every provider slot.

Args:
    cancellation: Optional shared cooperative cancellation token. Completed
        provider outcomes remain available when cancellation is observed.

Returns:
    Typed response in authored provider order. A completed scheduler can
    contain failed providers or partial extraction; inspect outcomes and
    coverage.

Raises:
    SearchError: Policy resolution or execution setup fails before a response.
    pydantic.ValidationError: Native response data cannot form a typed result.

[Source: python/yosoi/search.py:666](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/search.py#L666-L685)
