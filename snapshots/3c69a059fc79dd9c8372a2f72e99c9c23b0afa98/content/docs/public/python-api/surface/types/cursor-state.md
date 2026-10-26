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

[Source: python/yosoi/surface.py:916](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L916-L939)

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
