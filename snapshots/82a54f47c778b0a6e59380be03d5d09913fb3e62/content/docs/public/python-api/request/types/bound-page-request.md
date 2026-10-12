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

[Source: python/yosoi/request.py:346](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/request.py#L346-L414)

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

[Source: python/yosoi/request.py:354](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/request.py#L354-L362)

### id

```python
@property
def id(self) -> RequestId:
```

Return the identity of the retained authored request.

[Source: python/yosoi/request.py:365](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/request.py#L365-L367)

### target

```python
@property
def target(self) -> WebTarget:
```

Return original target text without validating it or performing I/O.

[Source: python/yosoi/request.py:370](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/request.py#L370-L372)

### policy

```python
@property
def policy(self) -> Policy:
```

Return a policy copy whose edits do not change this binding.

[Source: python/yosoi/request.py:375](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/request.py#L375-L377)

### check

```python
def check(self) -> None:
```

Validate target and bound-policy snapshot without acquisition I/O.

Raises:
    RequestError: Request preparation or policy resolution fails.

[Source: python/yosoi/request.py:379](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/request.py#L379-L385)

### in_session

```python
def in_session(self, session: Session) -> BoundSessionRequest:
```

Use this bound Policy while borrowing the caller-owned Session.

[Source: python/yosoi/request.py:387](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/request.py#L387-L389)

### with_work

```python
def with_work(self, work: Work) -> BoundSessionRequest:
```

Use this bound Policy while borrowing the caller-owned Work lease.

[Source: python/yosoi/request.py:391](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/request.py#L391-L393)

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

[Source: python/yosoi/request.py:395](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/request.py#L395-L414)
