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

[Source: python/yosoi/policy.py:190](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L190-L216)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: DocumentSelectionKind = 'current'
documents: Annotated[tuple[DocumentRequest, ...], Field(max_length=4)] | None = Field(default=None, exclude_if=lambda value: value is None)
```
