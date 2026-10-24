---
title: "NestedFlow"
description: "yosoi.browser.NestedFlow Python API reference."
order: 0
---

`yosoi.browser.NestedFlow`

```python
class NestedFlow(ImmutableModel):
```

Execute a nested Flow within its enclosing invocation.

Attributes:
    kind: Wire discriminator identifying this declaration.
    flow: Nested declaration retaining its own steps and continuation scope.

[Source: python/yosoi/browser.py:526](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L526-L535)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['nested_flow'] = 'nested_flow'
flow: Flow
```
