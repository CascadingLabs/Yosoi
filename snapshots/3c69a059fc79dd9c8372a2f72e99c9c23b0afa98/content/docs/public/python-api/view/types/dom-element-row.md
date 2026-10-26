---
title: "DomElementRow"
description: "yosoi.view.DomElementRow Python API reference."
order: 0
---

`yosoi.view.DomElementRow`

```python
class DomElementRow(ImmutableModel):
```

One exact DOM element reference with a bounded descendant text preview.

Attributes:
    ordinal: Zero-based element position in captured document order.
    node: Document-bound native locator coordinates.
    text_preview: At most 512 characters of retained descendant text.
    text_truncated: Whether the complete descendant text exceeded that bound.

[Source: python/yosoi/view.py:62](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/view.py#L62-L75)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
ordinal: int = Field(strict=True, ge=0, le=2 ** 64 - 1)
node: NodeReference
text_preview: StrictStr
text_truncated: StrictBool
```
