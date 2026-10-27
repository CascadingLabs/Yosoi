---
title: "CursorState"
description: "yosoi.surface.CursorState Python API reference."
order: 0
---

`yosoi.surface.CursorState`

```python
class CursorState(ImmutableModel):
```

Observable cursor status, never a transferable control capability.

[Source: python/yosoi/surface.py:1299](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L1299-L1322)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: CursorId = Field(description='Session-local cursor identity.')
live: StrictBool = Field(description='Whether the adapter has attached the session.')
hot: StrictBool = Field(description='Whether this cursor owns action authority.')
current_capture: StrictStr = Field(description='Current immutable capture identity.')
position: Position = Field(description='Saved region and focus.')
focus_freshness: Freshness = Field(description='Focus status against current evidence.')
scope_freshness: Freshness = Field(description='Scope status against current evidence.')
subscriptions: tuple[WatchState, ...] = Field(description="This cursor's bounded watches.")
action_in_flight: StrictBool = Field(description='Whether this cursor has a pending lease.')
```
