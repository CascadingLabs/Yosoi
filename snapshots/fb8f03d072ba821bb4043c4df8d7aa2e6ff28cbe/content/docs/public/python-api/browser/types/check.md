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

[Source: python/yosoi/browser.py:1855](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L1855-L1865)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
name: str
predicate: Callable[[Any], bool]
```
