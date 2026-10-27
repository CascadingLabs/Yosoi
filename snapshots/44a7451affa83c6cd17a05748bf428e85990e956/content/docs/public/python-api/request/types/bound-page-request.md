---
title: "BoundPageRequest"
description: "yosoi.request.BoundPageRequest Python API reference."
order: 0
---

`yosoi.request.BoundPageRequest`

```python
class BoundPageRequest:
```

A page request bound to a serialized policy snapshot.

Attributes:
    request: Retained authored request. Later edits to the caller policy do not
        affect this binding.

[Source: python/yosoi/request.py:358](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/request.py#L358-L426)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, request: PageRequest, policy: Policy) -> None:
```

Retain the request and snapshot its policy without acquisition I/O.

Args:
    request: Authored acquisition request to retain.
    policy: Complete declaration to serialize for subsequent checks and sends.

[Source: python/yosoi/request.py:366](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/request.py#L366-L374)

### id

```python
@property
def id(self) -> RequestId:
```

Return the identity of the retained authored request.

[Source: python/yosoi/request.py:377](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/request.py#L377-L379)

### target

```python
@property
def target(self) -> WebTarget:
```

Return original target text without validating it or performing I/O.

[Source: python/yosoi/request.py:382](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/request.py#L382-L384)

### policy

```python
@property
def policy(self) -> Policy:
```

Return a policy copy whose edits do not change this binding.

[Source: python/yosoi/request.py:387](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/request.py#L387-L389)

### check

```python
def check(self) -> None:
```

Validate target and bound-policy snapshot without acquisition I/O.

Raises:
    RequestError: Request preparation or policy resolution fails.

[Source: python/yosoi/request.py:391](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/request.py#L391-L397)

### in_session

```python
def in_session(self, session: Session) -> BoundSessionRequest:
```

Use this bound Policy while borrowing the caller-owned Session.

[Source: python/yosoi/request.py:399](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/request.py#L399-L401)

### with_work

```python
def with_work(self, work: Work) -> BoundSessionRequest:
```

Use this bound Policy while borrowing the caller-owned Work lease.

[Source: python/yosoi/request.py:403](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/request.py#L403-L405)

### send

```python
async def send(self, *, cancellation: CancellationToken | None=None) -> Response:
```

Acquire document representations with the bound policy.

Args:
    cancellation: Optional cooperative token shared with other operations.
        Observed cancellation retains prior attempts and marks later attempts
        not started; external effects are not rolled back.

Returns:
    Typed response retaining document owners. Completed termination does not
    imply that every attempt succeeded; inspect attempts and document outcomes.

Raises:
    RequestError: Preparation or adapter setup fails before execution.
    pydantic.ValidationError: Native response data cannot form a typed result.

[Source: python/yosoi/request.py:407](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/request.py#L407-L426)
