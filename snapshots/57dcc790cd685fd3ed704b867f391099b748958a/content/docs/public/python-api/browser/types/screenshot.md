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

[Source: python/yosoi/browser.py:219](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/browser.py#L219-L226)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['screenshot'] = 'screenshot'
```
