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

[Source: python/yosoi/browser.py:1855](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L1855-L1865)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
name: str
predicate: Callable[[Any], bool]
```
