---
title: "Condition"
description: "yosoi.browser.Condition Python API reference."
order: 0
---

`yosoi.browser.Condition`

```python
Condition = Annotated[Exists | Visible | CountAtLeast, Field(discriminator='kind')]
```

DOM condition tagged as existence, visibility, or minimum match count.

[Source: python/yosoi/browser.py:135](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L135-L135)
