---
title: "Cursor"
description: "yosoi.surface.Cursor Python API reference."
order: 0
---

`yosoi.surface.Cursor`

```python
class Cursor:
```

Owned navigation cursor. Close it to release watches and hot authority.

[Source: python/yosoi/surface.py:1425](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1425-L1556)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, handle: _native.SurfaceCursor) -> None:
```

Wrap a cursor allocated by Session.cursor.

[Source: python/yosoi/surface.py:1428](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1428-L1430)

### __enter__

```python
def __enter__(self) -> Self:
```

Use a cursor with deterministic cleanup.

[Source: python/yosoi/surface.py:1432](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1432-L1434)

### __exit__

```python
def __exit__(self, *_: object) -> None:
```

Release this cursor even when the body raises.

[Source: python/yosoi/surface.py:1436](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1436-L1443)

### id

```python
@property
def id(self) -> int:
```

Return a session-local diagnostic identity, without authority.

[Source: python/yosoi/surface.py:1446](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1446-L1448)

### status

```python
@property
def status(self) -> CursorState:
```

Inspect attachment, authority, subscriptions and evidence freshness.

[Source: python/yosoi/surface.py:1451](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1451-L1453)

### position

```python
@property
def position(self) -> Position:
```

Return the saved region, focus and continuation.

[Source: python/yosoi/surface.py:1456](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1456-L1458)

### overview

```python
def overview(self, *, continuation: Continuation | None=None, budget: Budget | None=None) -> NativePage:
```

Read current evidence and save its navigation continuation.

[Source: python/yosoi/surface.py:1476](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1476-L1482)

### find

```python
def find(self, query: str, *, continuation: Continuation | None=None, budget: Budget | None=None) -> NativePage:
```

Search current captured evidence without promoting the cursor.

[Source: python/yosoi/surface.py:1484](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1484-L1494)

### expand

```python
def expand(self, reference: NativeReference, *, continuation: Continuation | None=None, budget: Budget | None=None) -> NativePage:
```

Drill into evidence and save scope without granting action authority.

[Source: python/yosoi/surface.py:1496](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1496-L1506)

### inspect

```python
def inspect(self, reference: NativeReference, *, continuation: Continuation | None=None, budget: Budget | None=None) -> NativeInspection:
```

Read exact captured detail and save focus, preserving its freshness.

[Source: python/yosoi/surface.py:1508](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1508-L1518)

### focus

```python
def focus(self, reference: NativeReference) -> None:
```

Select exact evidence; this does not prove current UI eligibility.

[Source: python/yosoi/surface.py:1520](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1520-L1522)

### subscribe

```python
def subscribe(self, reference: NativeReference) -> int:
```

Watch a captured block; an adapter must publish and reconcile updates.

[Source: python/yosoi/surface.py:1524](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1524-L1526)

### reconcile

```python
def reconcile(self, watch: int, replacement: NativeReference) -> EventKind:
```

Compare replacement evidence without asserting durable entity identity.

[Source: python/yosoi/surface.py:1528](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1528-L1532)

### unsubscribe

```python
def unsubscribe(self, watch: int) -> None:
```

Remove this cursor's subscription without moving its focus.

[Source: python/yosoi/surface.py:1534](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1534-L1536)

### events

```python
def events(self) -> EventBatch:
```

Consume retained events; lost is true when unread history was evicted.

[Source: python/yosoi/surface.py:1538](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1538-L1540)

### promote

```python
def promote(self) -> None:
```

Acquire the single hot slot; detached or competing owners are rejected.

[Source: python/yosoi/surface.py:1542](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1542-L1544)

### cool

```python
def cool(self) -> None:
```

Release hot authority; an in-flight action prevents unsafe handoff.

[Source: python/yosoi/surface.py:1546](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1546-L1548)

### begin_action

```python
def begin_action(self) -> ActionLease:
```

Lease focus; the adapter still checks visibility and eligibility.

[Source: python/yosoi/surface.py:1550](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1550-L1552)

### close

```python
def close(self) -> None:
```

Release owned cursor state; further cursor operations are rejected.

[Source: python/yosoi/surface.py:1554](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1554-L1556)
