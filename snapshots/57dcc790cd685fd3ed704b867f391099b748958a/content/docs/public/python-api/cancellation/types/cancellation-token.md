---
title: "CancellationToken"
description: "yosoi.cancellation.CancellationToken Python API reference."
order: 0
---

`yosoi.cancellation.CancellationToken`

```python
class CancellationToken:
```

Share a caller-controlled cancellation signal with SDK operations.

Operations observe the signal cooperatively. Cancelling does not roll back
completed work or guarantee that external effects are undone. Keep the token
and pass it to operations that should share the same cancellation boundary.

[Source: python/yosoi/cancellation.py:8](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/cancellation.py#L8-L31)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self) -> None:
```

Create an independent token whose cancellation signal is unset.

[Source: python/yosoi/cancellation.py:16](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/cancellation.py#L16-L18)

### cancelled

```python
@property
def cancelled(self) -> bool:
```

Return whether cancellation has been requested for this token.

[Source: python/yosoi/cancellation.py:21](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/cancellation.py#L21-L23)

### cancel

```python
def cancel(self) -> None:
```

Request cancellation for operations sharing this token.

Calling this method repeatedly is harmless. It returns immediately;
operations finish observing cancellation asynchronously.

[Source: python/yosoi/cancellation.py:25](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/cancellation.py#L25-L31)
