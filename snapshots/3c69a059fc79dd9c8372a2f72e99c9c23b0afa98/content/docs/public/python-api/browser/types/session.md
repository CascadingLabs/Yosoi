---
title: "Session"
description: "yosoi.browser.Session Python API reference."
order: 0
---

`yosoi.browser.Session`

```python
class Session:
```

An acquired Rust Session, released by async context exit.

This Python bridge exposes one Work lease at a time. Rust watcher streams
and explicit tab creation are not exposed through this first pass.
Omitted settings inherit the bound policy's browser mode; explicit settings
retain their configured mode and must agree with that policy.

Attributes:
    policy: Policy serialized when acquisition or operations require it.
    settings: Optional retained Session settings, or None to use native defaults.

[Source: python/yosoi/browser.py:2169](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L2169-L2355)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, policy: Policy | None=None, settings: SessionPolicy | None=None, *, cancellation: CancellationToken | None=None) -> None:
```

Prepare a Session owner without acquiring a browser yet.

Args:
    policy: Policy serialized on acquisition; None creates the default policy.
    settings: Optional Session settings, with mode agreeing with the policy.
    cancellation: Default cancellation token for acquisition and operations.

Raises:
    TypeError: An argument has the wrong SDK type.

[Source: python/yosoi/browser.py:2182](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L2182-L2210)

### __aenter__

```python
async def __aenter__(self) -> Session:
```

Acquire the native browser Session and return this owner.

Raises:
    BrowserError: This Session is already acquired or acquisition fails.

[Source: python/yosoi/browser.py:2212](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L2212-L2225)

### __aexit__

```python
async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> Literal[False]:
```

Close the owned Session and preserve the context's original exception.

Args:
    exc_type: Exception type supplied by async context management.
    exc: Original operation exception, if any.
    traceback: Original traceback supplied by async context management.

Returns:
    False so successful cleanup does not suppress the original exception.

Raises:
    BrowserCleanupError: Cleanup fails while an original exception is active.

[Source: python/yosoi/browser.py:2227](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L2227-L2252)

### closed

```python
@property
def closed(self) -> bool:
```

Return whether no native handle is held, including before first entry.

[Source: python/yosoi/browser.py:2255](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L2255-L2257)

### work

```python
def work(self) -> Work:
```

Create a lazy Work wrapper for this acquired Session.

Returns:
    Caller-owned wrapper; control is acquired on entry or its first operation.

Raises:
    BrowserError: The Session has not been entered or is closed.

[Source: python/yosoi/browser.py:2259](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L2259-L2270)

### run

```python
async def run(self, flow: Flow, *, policy: Policy | None=None, cancellation: CancellationToken | None=None) -> FlowOutcome:
```

Run on an explicitly leased Work control, then release that lease.

[Source: python/yosoi/browser.py:2272](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L2272-L2281)

### invoke

```python
async def invoke(self, flow: Flow, *, policy: Policy | None=None, cancellation: CancellationToken | None=None) -> FlowOutcome:
```

Run a Flow with temporary Work ownership, retaining this Session.

Args:
    flow: Declaration executed on this Session's leased tab.
    policy: Optional operation policy; None inherits the Session policy.
    cancellation: Explicit token, or the Session token when omitted.

Returns:
    Flow outcome after the temporary Work lease is released.

Raises:
    BrowserError: Work acquisition or native invocation fails.
    BrowserCleanupError: Lease cleanup fails after an operation exception.

[Source: python/yosoi/browser.py:2283](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L2283-L2304)

### send

```python
async def send(self, request: PageRequest | BoundPageRequest, *, cancellation: CancellationToken | None=None) -> Response:
```

Send a PageRequest through this retained Session without closing it.

[Source: python/yosoi/browser.py:2306](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L2306-L2324)

### close

```python
async def close(self) -> None:
```

Await owned Session cleanup, then clear its native handle.

Repeated calls on a closed Session are harmless. Cleanup settlement is shielded
from caller task cancellation; cancellation is re-raised after settlement.
Closing does not undo already dispatched browser operations.

Raises:
    BrowserError: Native cleanup fails; retained state is not claimed closed.
    BrowserCleanupError: Cleanup fails while caller cancellation is pending.

[Source: python/yosoi/browser.py:2326](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L2326-L2355)
