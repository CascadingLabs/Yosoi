---
title: "Visible"
description: "yosoi.browser.Visible Python API reference."
order: 0
---

`yosoi.browser.Visible`

```python
class Visible(ImmutableModel):
```

Declare that a matching element must satisfy browser visibility checks.

Attributes:
    kind: Wire discriminator identifying this declaration.
    selector: CSS selector identifying elements on the current browser page.

[Source: python/yosoi/browser.py:106](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L106-L115)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['visible'] = 'visible'
selector: StrictStr = Field(min_length=1, max_length=4096)
```
