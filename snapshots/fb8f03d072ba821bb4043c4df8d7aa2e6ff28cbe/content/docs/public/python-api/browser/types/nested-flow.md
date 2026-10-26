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

[Source: python/yosoi/browser.py:529](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L529-L538)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['nested_flow'] = 'nested_flow'
flow: Flow
```
