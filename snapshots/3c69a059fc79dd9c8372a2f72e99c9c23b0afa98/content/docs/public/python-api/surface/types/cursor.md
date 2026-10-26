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

[Source: python/yosoi/surface.py:1028](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1028-L1159)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, handle: _native.SurfaceCursor) -> None:
```

Wrap a cursor allocated by Session.cursor.

[Source: python/yosoi/surface.py:1031](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1031-L1033)

### __enter__

```python
def __enter__(self) -> Self:
```

Use a cursor with deterministic cleanup.

[Source: python/yosoi/surface.py:1035](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1035-L1037)

### __exit__

```python
def __exit__(self, *_: object) -> None:
```

Release this cursor even when the body raises.

[Source: python/yosoi/surface.py:1039](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1039-L1046)

### id

```python
@property
def id(self) -> int:
```

Return a session-local diagnostic identity, without authority.

[Source: python/yosoi/surface.py:1049](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1049-L1051)

### status

```python
@property
def status(self) -> CursorState:
```

Inspect attachment, authority, subscriptions and evidence freshness.

[Source: python/yosoi/surface.py:1054](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1054-L1056)

### position

```python
@property
def position(self) -> Position:
```

Return the saved region, focus and continuation.

[Source: python/yosoi/surface.py:1059](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1059-L1061)

### overview

```python
def overview(self, *, continuation: Continuation | None=None, budget: Budget | None=None) -> NativePage:
```

Read current evidence and save its navigation continuation.

[Source: python/yosoi/surface.py:1079](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1079-L1085)

### find

```python
def find(self, query: str, *, continuation: Continuation | None=None, budget: Budget | None=None) -> NativePage:
```

Search current captured evidence without promoting the cursor.

[Source: python/yosoi/surface.py:1087](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1087-L1097)

### expand

```python
def expand(self, reference: NativeReference, *, continuation: Continuation | None=None, budget: Budget | None=None) -> NativePage:
```

Drill into evidence and save scope without granting action authority.

[Source: python/yosoi/surface.py:1099](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1099-L1109)

### inspect

```python
def inspect(self, reference: NativeReference, *, continuation: Continuation | None=None, budget: Budget | None=None) -> NativeInspection:
```

Read exact captured detail and save focus, preserving its freshness.

[Source: python/yosoi/surface.py:1111](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1111-L1121)

### focus

```python
def focus(self, reference: NativeReference) -> None:
```

Select exact evidence; this does not prove current UI eligibility.

[Source: python/yosoi/surface.py:1123](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1123-L1125)

### subscribe

```python
def subscribe(self, reference: NativeReference) -> int:
```

Watch a captured block; an adapter must publish and reconcile updates.

[Source: python/yosoi/surface.py:1127](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1127-L1129)

### reconcile

```python
def reconcile(self, watch: int, replacement: NativeReference) -> EventKind:
```

Compare replacement evidence without asserting durable entity identity.

[Source: python/yosoi/surface.py:1131](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1131-L1135)

### unsubscribe

```python
def unsubscribe(self, watch: int) -> None:
```

Remove this cursor's subscription without moving its focus.

[Source: python/yosoi/surface.py:1137](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1137-L1139)

### events

```python
def events(self) -> EventBatch:
```

Consume retained events; lost is true when unread history was evicted.

[Source: python/yosoi/surface.py:1141](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1141-L1143)

### promote

```python
def promote(self) -> None:
```

Acquire the single hot slot; detached or competing owners are rejected.

[Source: python/yosoi/surface.py:1145](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1145-L1147)

### cool

```python
def cool(self) -> None:
```

Release hot authority; an in-flight action prevents unsafe handoff.

[Source: python/yosoi/surface.py:1149](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1149-L1151)

### begin_action

```python
def begin_action(self) -> ActionLease:
```

Lease focus; the adapter still checks visibility and eligibility.

[Source: python/yosoi/surface.py:1153](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1153-L1155)

### close

```python
def close(self) -> None:
```

Release owned cursor state; further cursor operations are rejected.

[Source: python/yosoi/surface.py:1157](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1157-L1159)
