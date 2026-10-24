---
title: "Exists"
description: "yosoi.browser.Exists Python API reference."
order: 0
---

`yosoi.browser.Exists`

```python
class Exists(ImmutableModel):
```

Declare that at least one matching DOM element must exist.

Existence does not imply visibility, readiness, or business success.

Attributes:
    kind: Wire discriminator identifying this declaration.
    selector: CSS selector identifying elements on the current browser page.

[Source: python/yosoi/browser.py:92](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L92-L103)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['exists'] = 'exists'
selector: StrictStr = Field(min_length=1, max_length=4096)
```
