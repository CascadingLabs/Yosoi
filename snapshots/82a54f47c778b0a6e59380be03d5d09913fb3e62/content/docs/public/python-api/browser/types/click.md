---
title: "Click"
description: "yosoi.browser.Click Python API reference."
order: 0
---

`yosoi.browser.Click`

```python
class Click(TriggerStep):
```

Declare a single click on the current browser page.

Dispatching a click does not prove that its intended effect occurred. Use Until with
an explicit domain expectation to observe that effect.

Attributes:
    kind: Wire discriminator identifying this declaration.
    selector: CSS selector identifying elements on the current browser page.

[Source: python/yosoi/browser.py:176](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L176-L188)

## Base classes

[TriggerStep](/yosoi/python-api/browser/types/trigger-step/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['click'] = 'click'
selector: StrictStr = Field(min_length=1, max_length=4096)
```
