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

[Source: python/yosoi/surface.py:906](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L906-L913)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: WatchId = Field(description='Session-local watch identity.')
reference: NativeReference = Field(description='Last reconciled captured region.')
needs_reconciliation: StrictBool = Field(description='Whether a new capture needs comparison.')
```
