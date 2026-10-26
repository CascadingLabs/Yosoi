---
title: "Screenshot"
description: "yosoi.browser.Screenshot Python API reference."
order: 0
---

`yosoi.browser.Screenshot`

```python
class Screenshot(ImmutableModel):
```

Declare screenshot capture from the current browser tab.

Attributes:
    kind: Wire discriminator identifying this declaration.

[Source: python/yosoi/browser.py:222](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L222-L229)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['screenshot'] = 'screenshot'
```
