---
title: "DocumentSelection"
description: "yosoi.policy.DocumentSelection Python API reference."
order: 0
---

`yosoi.policy.DocumentSelection`

```python
class DocumentSelection(Model):
```

Current or explicit document outputs for one acquisition.

Attributes:
    kind: current resolves package defaults; exact retains an authored output
        selection.
    documents: None for current selection; an explicit bounded tuple for exact
        selection, including an intentionally empty tuple.

[Source: python/yosoi/policy.py:178](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L178-L204)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: DocumentSelectionKind = 'current'
documents: Annotated[tuple[DocumentRequest, ...], Field(max_length=4)] | None = Field(default=None, exclude_if=lambda value: value is None)
```
