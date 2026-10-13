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

[Source: python/yosoi/browser.py:132](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/browser.py#L132-L132)
