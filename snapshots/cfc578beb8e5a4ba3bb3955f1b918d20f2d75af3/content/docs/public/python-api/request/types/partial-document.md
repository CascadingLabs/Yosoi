---
title: "PartialDocument"
description: "yosoi.request.PartialDocument Python API reference."
order: 0
---

`yosoi.request.PartialDocument`

```python
class PartialDocument(ImmutableModel):
```

Document production retained incomplete evidence or omitted a document.

Attributes:
    status: Discriminator fixed to partial for tagged decoding.
    document: Retained partial document, or None when no usable document was
        retained.
    reasons: Typed reasons limiting production completeness. Partial is not complete
        absence.

[Source: python/yosoi/request.py:107](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/request.py#L107-L120)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['partial']
document: Document | None
reasons: tuple[ProjectionReason, ...]
```
