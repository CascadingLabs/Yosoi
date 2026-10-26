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

[Source: python/yosoi/browser.py:526](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L526-L535)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['nested_flow'] = 'nested_flow'
flow: Flow
```
