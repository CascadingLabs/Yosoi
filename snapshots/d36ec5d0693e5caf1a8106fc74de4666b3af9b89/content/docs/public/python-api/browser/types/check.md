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

[Source: python/yosoi/browser.py:1855](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L1855-L1865)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
name: str
predicate: Callable[[Any], bool]
```
