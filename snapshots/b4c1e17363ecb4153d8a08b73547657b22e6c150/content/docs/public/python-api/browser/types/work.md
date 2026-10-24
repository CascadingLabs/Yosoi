---
title: "Work"
description: "yosoi.browser.Work Python API reference."
order: 0
---

`yosoi.browser.Work`

```python
class Work:
```

An explicit browser control lease owned by one Session.

Explicit cancellation bounds the current Flow scope. It does not undo a
dispatched operation or close the caller-owned Session.

[Source: python/yosoi/browser.py:2358](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L2358-L2554)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, session: Session) -> None:
```

Prepare a lazy control lease tied to a caller-owned Session.

Args:
    session: Session whose tab authority will be borrowed on acquisition.

No control is acquired until context entry or the first operation.

[Source: python/yosoi/browser.py:2365](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L2365-L2378)

### __aenter__

```python
async def __aenter__(self) -> Work:
```

Acquire serialized Work control and return this wrapper.

Raises:
    BrowserError: Work was released, the Session is closed, or acquisition
        fails.

[Source: python/yosoi/browser.py:2380](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L2380-L2389)

### __aexit__

```python
async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> Literal[False]:
```

Release control without closing the caller-owned Session.

Args:
    exc_type: Exception type supplied by async context management.
    exc: Original operation exception, if any.
    traceback: Original traceback supplied by async context management.

Returns:
    False so successful release does not suppress an original exception.

Raises:
    BrowserCleanupError: Release fails while an original exception is active.

[Source: python/yosoi/browser.py:2391](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L2391-L2416)

### released

```python
@property
def released(self) -> bool:
```

Return whether release has settled; a released wrapper cannot reacquire.

[Source: python/yosoi/browser.py:2419](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L2419-L2421)

### run

```python
async def run(self, flow: Flow, *, policy: Policy | None=None, cancellation: CancellationToken | None=None) -> FlowOutcome:
```

Invoke a Flow through this retained Work lease.

Args:
    flow: Declaration executed on the borrowed tab.
    policy: Optional operation policy; None inherits the Session policy.
    cancellation: Explicit token, or the Session token when omitted.

Returns:
    Flow outcome; this method retains the Work lease and owning Session.

[Source: python/yosoi/browser.py:2423](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L2423-L2440)

### invoke

```python
async def invoke(self, flow: Flow, *, policy: Policy | None=None, cancellation: CancellationToken | None=None) -> FlowOutcome:
```

Execute serialized Flow work without releasing caller-owned control.

Args:
    flow: Declaration executed after lazy Work acquisition if needed.
    policy: Optional operation policy; None inherits the Session policy.
    cancellation: Explicit token, or the Session token when omitted.

Returns:
    Outcome retaining partial and unknown facts. Cancellation does not roll
    back dispatched effects or close the owning Session.

Raises:
    BrowserError: Work is unavailable or native invocation fails.
    FlowInvocationError: Native failure carries partial or cleanup evidence.

[Source: python/yosoi/browser.py:2442](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L2442-L2464)

### send

```python
async def send(self, request: PageRequest | BoundPageRequest, *, cancellation: CancellationToken | None=None) -> Response:
```

Send a PageRequest on this borrowed Work without releasing the lease.

[Source: python/yosoi/browser.py:2466](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L2466-L2490)

### release

```python
async def release(self) -> None:
```

Await native control release while retaining the owning Session.

Repeated calls are harmless. The wrapper becomes permanently released after
settlement. Caller task cancellation is shielded during release and re-raised
afterward; release does not undo dispatched effects.

Raises:
    BrowserError: Native release fails; settlement is not claimed successful.
    BrowserCleanupError: Release fails while caller cancellation is pending.

[Source: python/yosoi/browser.py:2509](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L2509-L2541)
