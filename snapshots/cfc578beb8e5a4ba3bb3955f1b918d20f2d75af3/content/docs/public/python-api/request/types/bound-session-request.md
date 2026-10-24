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

[Source: python/yosoi/request.py:429](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/request.py#L429-L513)

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

[Source: python/yosoi/request.py:441](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/request.py#L441-L473)

### id

```python
@property
def id(self) -> RequestId:
```

Return the identity of the retained authored request.

[Source: python/yosoi/request.py:476](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/request.py#L476-L478)

### target

```python
@property
def target(self) -> WebTarget:
```

Return original target text, which can contain user-sensitive data.

[Source: python/yosoi/request.py:481](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/request.py#L481-L483)

### policy

```python
@property
def policy(self) -> Policy | None:
```

Return a policy copy when explicitly bound, otherwise None.

[Source: python/yosoi/request.py:486](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/request.py#L486-L490)

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

[Source: python/yosoi/request.py:492](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/request.py#L492-L513)
