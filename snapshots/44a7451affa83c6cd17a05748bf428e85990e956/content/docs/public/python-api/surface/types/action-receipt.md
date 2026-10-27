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

[Source: python/yosoi/surface.py:1350](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L1350-L1360)

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
