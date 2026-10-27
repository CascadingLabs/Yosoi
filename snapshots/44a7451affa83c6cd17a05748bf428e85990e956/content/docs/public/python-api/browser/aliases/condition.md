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

[Source: python/yosoi/browser.py:135](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L135-L135)
