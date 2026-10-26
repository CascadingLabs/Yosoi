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

[Source: python/yosoi/browser.py:222](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L222-L229)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['screenshot'] = 'screenshot'
```
