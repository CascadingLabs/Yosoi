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

[Source: python/yosoi/request.py:279](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/request.py#L279-L343)

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

[Source: python/yosoi/request.py:290](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/request.py#L290-L292)

### id

```python
@property
def id(self) -> RequestId:
```

Return the request identity retained across policy bindings and sends.

[Source: python/yosoi/request.py:295](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/request.py#L295-L297)

### check

```python
def check(self) -> None:
```

Validate target and package-default policy without acquisition I/O.

Raises:
    RequestError: Request preparation or policy resolution fails.

[Source: python/yosoi/request.py:299](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/request.py#L299-L305)

### bind

```python
def bind(self, policy: Policy) -> BoundPageRequest:
```

Snapshot a complete policy declaration for subsequent acquisition.

Args:
    policy: Complete declaration to serialize at binding time.

Returns:
    A binding unaffected by later edits to the caller policy.

[Source: python/yosoi/request.py:307](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/request.py#L307-L316)

### in_session

```python
def in_session(self, session: Session) -> BoundSessionRequest:
```

Bind this request to the caller-owned browser Session.

[Source: python/yosoi/request.py:318](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/request.py#L318-L320)

### with_work

```python
def with_work(self, work: Work) -> BoundSessionRequest:
```

Bind this request to the caller-owned Work lease.

[Source: python/yosoi/request.py:322](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/request.py#L322-L324)

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

[Source: python/yosoi/request.py:326](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/request.py#L326-L343)
