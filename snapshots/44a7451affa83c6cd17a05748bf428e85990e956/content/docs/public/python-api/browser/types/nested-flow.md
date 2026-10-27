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

[Source: python/yosoi/browser.py:529](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L529-L538)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['nested_flow'] = 'nested_flow'
flow: Flow
```
