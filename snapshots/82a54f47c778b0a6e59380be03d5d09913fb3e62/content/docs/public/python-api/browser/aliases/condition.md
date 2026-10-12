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

[Source: python/yosoi/browser.py:132](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L132-L132)
