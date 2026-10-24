---
title: "Navigate"
description: "yosoi.browser.Navigate Python API reference."
order: 0
---

`yosoi.browser.Navigate`

```python
class Navigate(ImmutableModel):
```

Declare navigation to a URL on the leased browser tab.

Attributes:
    kind: Wire discriminator identifying this declaration.
    url: Nonempty destination URL; construction does not navigate or acquire a tab.

[Source: python/yosoi/browser.py:164](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L164-L173)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['navigate'] = 'navigate'
url: StrictStr = Field(min_length=1)
```
