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

[Source: python/yosoi/surface.py:1162](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1162-L1197)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, handle: _native.SurfaceActionLease) -> None:
```

Wrap a Rust permit issued by a hot cursor.

[Source: python/yosoi/surface.py:1165](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1165-L1167)

### __enter__

```python
def __enter__(self) -> Self:
```

Keep the permit scoped to one adapter operation.

[Source: python/yosoi/surface.py:1169](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1169-L1171)

### __exit__

```python
def __exit__(self, *_: object) -> None:
```

Release unfinished authority on exceptions, retaining an outcome event.

[Source: python/yosoi/surface.py:1173](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1173-L1175)

### revalidate

```python
def revalidate(self) -> NativeReference:
```

Recheck live ownership and exact evidence immediately before dispatch.

[Source: python/yosoi/surface.py:1177](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1177-L1179)

### mark_dispatched

```python
def mark_dispatched(self) -> None:
```

Record that a native effect may have begun; this does not confirm success.

[Source: python/yosoi/surface.py:1181](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1181-L1183)

### finish

```python
def finish(self, status: ActionStatus, note: str) -> ActionReceipt:
```

Consume the permit with the adapter's observed outcome.

Confirmed requires dispatch; Rejected is forbidden after dispatch. Rust
rejects contradictory outcomes and preserves uncertainty when consumed.

[Source: python/yosoi/surface.py:1185](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1185-L1193)

### close

```python
def close(self) -> None:
```

Release an unfinished permit; repeated close is harmless.

[Source: python/yosoi/surface.py:1195](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L1195-L1197)
