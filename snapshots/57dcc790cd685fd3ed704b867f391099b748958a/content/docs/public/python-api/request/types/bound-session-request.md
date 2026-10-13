---
title: "BoundSessionRequest"
description: "yosoi.request.BoundSessionRequest Python API reference."
order: 0
---

`yosoi.request.BoundSessionRequest`

```python
class BoundSessionRequest:
```

A page request retaining a caller-owned browser Session or Work.

Attributes:
    request: Authored or policy-bound page request to send through the retained
        owner.

[Source: python/yosoi/request.py:417](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/request.py#L417-L501)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
request: PageRequest | BoundPageRequest
```

## Methods

### __init__

```python
def __init__(self, request: PageRequest | BoundPageRequest, *, session: Session | None=None, work: Work | None=None) -> None:
```

Retain exactly one caller-owned browser execution owner.

Args:
    request: Authored or policy-bound acquisition request.
    session: Browser Session to reuse, mutually exclusive with work.
    work: Browser Work lease to reuse, mutually exclusive with session.

Raises:
    TypeError: Both or neither owners are supplied, or an owner has the wrong
        type.

The caller controls the owner's lifetime. Construction starts no acquisition
and does not transfer responsibility for closing the Session or Work lease.

[Source: python/yosoi/request.py:429](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/request.py#L429-L461)

### id

```python
@property
def id(self) -> RequestId:
```

Return the identity of the retained authored request.

[Source: python/yosoi/request.py:464](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/request.py#L464-L466)

### target

```python
@property
def target(self) -> WebTarget:
```

Return original target text, which can contain user-sensitive data.

[Source: python/yosoi/request.py:469](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/request.py#L469-L471)

### policy

```python
@property
def policy(self) -> Policy | None:
```

Return a policy copy when explicitly bound, otherwise None.

[Source: python/yosoi/request.py:474](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/request.py#L474-L478)

### send

```python
async def send(self, *, cancellation: CancellationToken | None=None) -> Response:
```

Acquire documents through the retained Session or Work owner.

Args:
    cancellation: Optional cooperative token. When omitted, the owner applies
        its existing cancellation behavior. Observed cancellation preserves
        completed outcomes and does not undo external effects.

Returns:
    A typed response without closing the Session or releasing the Work lease.
    Inspect individual attempts rather than treating completion as success.

Raises:
    BrowserError: The Session has not been entered or Work is unavailable.
    RequestError: Request preparation or acquisition setup cannot begin.
    RuntimeError: The binding has lost both execution owners.

[Source: python/yosoi/request.py:480](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/request.py#L480-L501)
