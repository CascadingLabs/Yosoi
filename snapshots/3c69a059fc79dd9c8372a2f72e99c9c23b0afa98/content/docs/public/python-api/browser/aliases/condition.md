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

[Source: python/yosoi/browser.py:132](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L132-L132)
