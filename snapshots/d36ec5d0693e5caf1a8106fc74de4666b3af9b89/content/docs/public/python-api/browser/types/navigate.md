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

[Source: python/yosoi/browser.py:167](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L167-L176)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['navigate'] = 'navigate'
url: StrictStr = Field(min_length=1)
```
