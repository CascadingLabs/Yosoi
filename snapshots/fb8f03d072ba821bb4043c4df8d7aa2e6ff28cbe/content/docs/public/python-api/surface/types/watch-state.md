---
title: "WatchState"
description: "yosoi.surface.WatchState Python API reference."
order: 0
---

`yosoi.surface.WatchState`

```python
class WatchState(ImmutableModel):
```

One explicit subscription to captured regional evidence.

[Source: python/yosoi/surface.py:1289](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1289-L1296)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: WatchId = Field(description='Session-local watch identity.')
reference: NativeReference = Field(description='Last reconciled captured region.')
needs_reconciliation: StrictBool = Field(description='Whether a new capture needs comparison.')
```
