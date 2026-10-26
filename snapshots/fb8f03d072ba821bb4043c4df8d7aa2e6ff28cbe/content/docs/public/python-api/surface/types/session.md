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

[Source: python/yosoi/surface.py:1363](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1363-L1422)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, index: Surface, policy: SessionPolicy | None=None) -> None:
```

Create detached state with no action authority.

[Source: python/yosoi/surface.py:1374](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1374-L1378)

### cursor

```python
def cursor(self) -> Cursor:
```

Allocate a reader within policy; Rust rejects capacity exhaustion.

[Source: python/yosoi/surface.py:1380](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1380-L1382)

### attach

```python
def attach(self) -> None:
```

Declare the external observer live, without promoting any cursor.

[Source: python/yosoi/surface.py:1384](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1384-L1386)

### detach

```python
def detach(self) -> None:
```

Detach observation and revoke hot authority and pending leases.

[Source: python/yosoi/surface.py:1388](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1388-L1390)

### invalidate

```python
def invalidate(self, reason: str) -> None:
```

Mark observation uncertain until an adapter publishes fresh evidence.

[Source: python/yosoi/surface.py:1392](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1392-L1394)

### publish

```python
def publish(self, index: Surface) -> None:
```

Publish a new immutable capture, invalidating stale focused evidence.

[Source: python/yosoi/surface.py:1396](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1396-L1398)

### outcome

```python
def outcome(self) -> Outcome | None:
```

Snapshot retained evidence, or return None when archive policy is off.

[Source: python/yosoi/surface.py:1400](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1400-L1403)

### close

```python
def close(self) -> Outcome | None:
```

Close logical readers and return the final policy outcome.

This revokes authority and preserves pending effects as unknown. External
provider cleanup remains caller-owned. Repeated calls return the same data.

[Source: python/yosoi/surface.py:1405](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1405-L1412)

### current

```python
@property
def current(self) -> Surface:
```

Return an immutable index safe to retain after subsequent publication.

[Source: python/yosoi/surface.py:1415](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1415-L1417)

### hot_owner

```python
@property
def hot_owner(self) -> int | None:
```

Return the single hot cursor identity, or None.

[Source: python/yosoi/surface.py:1420](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1420-L1422)
