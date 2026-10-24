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

[Source: python/yosoi/browser.py:164](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L164-L173)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['navigate'] = 'navigate'
url: StrictStr = Field(min_length=1)
```
