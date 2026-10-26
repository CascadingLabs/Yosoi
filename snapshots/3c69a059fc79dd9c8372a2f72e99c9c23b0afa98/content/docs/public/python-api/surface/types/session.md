---
title: "Session"
description: "yosoi.surface.Session Python API reference."
order: 0
---

`yosoi.surface.Session`

```python
class Session:
```

In-memory evidence session for an external live adapter.

Args:
    index: Initial immutable evidence.
    policy: Reader, history and event bounds, defaulting to one cursor.

Attaching declares that the adapter is observing its source. This class does
not launch a browser, install a DOM observer or dispatch actions by itself.

[Source: python/yosoi/surface.py:980](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L980-L1025)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, index: Surface, policy: SessionPolicy | None=None) -> None:
```

Create detached state with no action authority.

[Source: python/yosoi/surface.py:991](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L991-L995)

### cursor

```python
def cursor(self) -> Cursor:
```

Allocate a reader within policy; Rust rejects capacity exhaustion.

[Source: python/yosoi/surface.py:997](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L997-L999)

### attach

```python
def attach(self) -> None:
```

Declare the external observer live, without promoting any cursor.

[Source: python/yosoi/surface.py:1001](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1001-L1003)

### detach

```python
def detach(self) -> None:
```

Detach observation and revoke hot authority and pending leases.

[Source: python/yosoi/surface.py:1005](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1005-L1007)

### invalidate

```python
def invalidate(self, reason: str) -> None:
```

Mark observation uncertain until an adapter publishes fresh evidence.

[Source: python/yosoi/surface.py:1009](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1009-L1011)

### publish

```python
def publish(self, index: Surface) -> None:
```

Publish a new immutable capture, invalidating stale focused evidence.

[Source: python/yosoi/surface.py:1013](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1013-L1015)

### current

```python
@property
def current(self) -> Surface:
```

Return an immutable index safe to retain after subsequent publication.

[Source: python/yosoi/surface.py:1018](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1018-L1020)

### hot_owner

```python
@property
def hot_owner(self) -> int | None:
```

Return the single hot cursor identity, or None.

[Source: python/yosoi/surface.py:1023](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1023-L1025)
