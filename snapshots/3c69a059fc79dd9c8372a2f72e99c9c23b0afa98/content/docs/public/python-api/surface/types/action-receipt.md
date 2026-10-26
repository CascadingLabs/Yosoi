---
title: "ActionReceipt"
description: "yosoi.surface.ActionReceipt Python API reference."
order: 0
---

`yosoi.surface.ActionReceipt`

```python
class ActionReceipt(ImmutableModel):
```

Adapter-reported outcome preserving dispatch uncertainty separately.

[Source: python/yosoi/surface.py:967](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L967-L977)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
cursor: int = Field(description='Cursor that owned the lease.')
target: NativeReference = Field(description='Exact pre-dispatch target evidence.')
dispatched: StrictBool = Field(description='Whether the adapter marked dispatch.')
status: ActionStatus = Field(description='Reported postcondition or uncertainty.')
after_capture: StrictStr | None = Field(description='Current capture when finished.')
note: StrictStr = Field(description="Adapter's explanation of the result.")
```
