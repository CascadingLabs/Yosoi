---
title: "ActionLease"
description: "yosoi.surface.ActionLease Python API reference."
order: 0
---

`yosoi.surface.ActionLease`

```python
class ActionLease:
```

Owned one-action permit. Dropping or closing it preserves uncertain dispatch.

[Source: python/yosoi/surface.py:1559](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L1559-L1594)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, handle: _native.SurfaceActionLease) -> None:
```

Wrap a Rust permit issued by a hot cursor.

[Source: python/yosoi/surface.py:1562](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L1562-L1564)

### __enter__

```python
def __enter__(self) -> Self:
```

Keep the permit scoped to one adapter operation.

[Source: python/yosoi/surface.py:1566](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L1566-L1568)

### __exit__

```python
def __exit__(self, *_: object) -> None:
```

Release unfinished authority on exceptions, retaining an outcome event.

[Source: python/yosoi/surface.py:1570](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L1570-L1572)

### revalidate

```python
def revalidate(self) -> NativeReference:
```

Recheck live ownership and exact evidence immediately before dispatch.

[Source: python/yosoi/surface.py:1574](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L1574-L1576)

### mark_dispatched

```python
def mark_dispatched(self) -> None:
```

Record that a native effect may have begun; this does not confirm success.

[Source: python/yosoi/surface.py:1578](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L1578-L1580)

### finish

```python
def finish(self, status: ActionStatus, note: str) -> ActionReceipt:
```

Consume the permit with the adapter's observed outcome.

Confirmed requires dispatch; Rejected is forbidden after dispatch. Rust
rejects contradictory outcomes and preserves uncertainty when consumed.

[Source: python/yosoi/surface.py:1582](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L1582-L1590)

### close

```python
def close(self) -> None:
```

Release an unfinished permit; repeated close is harmless.

[Source: python/yosoi/surface.py:1592](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L1592-L1594)
