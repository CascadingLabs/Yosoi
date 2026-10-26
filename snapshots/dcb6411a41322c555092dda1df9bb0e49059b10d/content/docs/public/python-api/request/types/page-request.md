---
title: "PageRequest"
description: "yosoi.request.PageRequest Python API reference."
order: 0
---

`yosoi.request.PageRequest`

```python
class PageRequest(NativeAuthoringModel):
```

Authored page acquisition intent, independent of policy binding.

Attributes:
    target: Original target text. URL validation is deferred until checking or
        sending; construction does not perform I/O.

[Source: python/yosoi/request.py:291](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/request.py#L291-L355)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
target: WebTarget = Field(repr=False)
```

## Methods

### model_post_init

```python
def model_post_init(self, context: object) -> None:
```

Create a native request handle without acquiring or validating a URL.

[Source: python/yosoi/request.py:302](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/request.py#L302-L304)

### id

```python
@property
def id(self) -> RequestId:
```

Return the request identity retained across policy bindings and sends.

[Source: python/yosoi/request.py:307](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/request.py#L307-L309)

### check

```python
def check(self) -> None:
```

Validate target and package-default policy without acquisition I/O.

Raises:
    RequestError: Request preparation or policy resolution fails.

[Source: python/yosoi/request.py:311](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/request.py#L311-L317)

### bind

```python
def bind(self, policy: Policy) -> BoundPageRequest:
```

Snapshot a complete policy declaration for subsequent acquisition.

Args:
    policy: Complete declaration to serialize at binding time.

Returns:
    A binding unaffected by later edits to the caller policy.

[Source: python/yosoi/request.py:319](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/request.py#L319-L328)

### in_session

```python
def in_session(self, session: Session) -> BoundSessionRequest:
```

Bind this request to the caller-owned browser Session.

[Source: python/yosoi/request.py:330](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/request.py#L330-L332)

### with_work

```python
def with_work(self, work: Work) -> BoundSessionRequest:
```

Bind this request to the caller-owned Work lease.

[Source: python/yosoi/request.py:334](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/request.py#L334-L336)

### send

```python
async def send(self, *, cancellation: CancellationToken | None=None) -> Response:
```

Acquire document representations with defaults.

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

[Source: python/yosoi/request.py:338](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/request.py#L338-L355)
