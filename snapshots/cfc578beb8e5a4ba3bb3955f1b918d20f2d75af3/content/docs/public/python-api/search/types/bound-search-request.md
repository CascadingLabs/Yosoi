---
title: "BoundSearchRequest"
description: "yosoi.search.BoundSearchRequest Python API reference."
order: 0
---

`yosoi.search.BoundSearchRequest`

```python
class BoundSearchRequest:
```

A request with a serialized snapshot of a complete policy declaration.

Attributes:
    request: Retained query request. Changing the caller policy later does not
        affect this binding.

[Source: python/yosoi/search.py:688](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/search.py#L688-L748)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, request: SearchRequest, policy: Policy) -> None:
```

Retain the query request and serialize the policy without provider I/O.

Args:
    request: Authored query request to retain.
    policy: Complete declaration to snapshot for subsequent checks and sends.

[Source: python/yosoi/search.py:696](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/search.py#L696-L704)

### id

```python
@property
def id(self) -> str:
```

Return the identity of the retained query request.

[Source: python/yosoi/search.py:707](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/search.py#L707-L709)

### query

```python
@property
def query(self) -> str:
```

Return the original authored query; it can contain user-sensitive text.

[Source: python/yosoi/search.py:712](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/search.py#L712-L714)

### policy

```python
@property
def policy(self) -> Policy:
```

Return a policy copy whose edits do not affect this binding.

[Source: python/yosoi/search.py:717](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/search.py#L717-L719)

### check

```python
def check(self) -> None:
```

Validate against the bound policy snapshot without sending provider requests.

Raises:
    SearchError: Provider selection, policy resolution, or execution setup is
        invalid.

[Source: python/yosoi/search.py:721](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/search.py#L721-L728)

### send

```python
async def send(self, *, cancellation: CancellationToken | None=None) -> SearchResponse:
```

Run providers selected by the bound policy snapshot.

Args:
    cancellation: Optional cooperative token shared with other operations.
        Observed cancellation retains completed results and unstarted slots.

Returns:
    Typed response in authored provider order, including failures and partial
    results. Inspect termination separately from each provider outcome.

Raises:
    SearchError: Policy resolution or execution setup fails before a response.
    pydantic.ValidationError: Native response data cannot form a typed result.

[Source: python/yosoi/search.py:730](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/search.py#L730-L748)
