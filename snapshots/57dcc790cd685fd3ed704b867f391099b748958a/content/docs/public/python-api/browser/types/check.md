---
title: "Check"
description: "yosoi.browser.Check Python API reference."
order: 0
---

`yosoi.browser.Check`

```python
class Check:
```

Name a synchronous local predicate for Contract assertions.

Attributes:
    name: Short diagnostic name recorded when a check fails.
    predicate: Synchronous callable evaluating a validated record and returning a
        boolean.

[Source: python/yosoi/browser.py:1756](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/browser.py#L1756-L1766)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
name: str
predicate: Callable[[Any], bool]
```
