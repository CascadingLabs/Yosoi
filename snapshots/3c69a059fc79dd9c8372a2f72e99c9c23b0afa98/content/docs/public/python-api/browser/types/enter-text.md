---
title: "EnterText"
description: "yosoi.browser.EnterText Python API reference."
order: 0
---

`yosoi.browser.EnterText`

```python
class EnterText(TriggerStep):
```

Declare text input on the current browser page.

Attributes:
    kind: Wire discriminator identifying this declaration.
    selector: CSS selector identifying elements on the current browser page.
    text: Text passed to the browser input action; an empty string is permitted.

[Source: python/yosoi/browser.py:191](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L191-L202)

## Base classes

[TriggerStep](/yosoi/python-api/browser/types/trigger-step/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['enter_text'] = 'enter_text'
selector: StrictStr = Field(min_length=1, max_length=4096)
text: StrictStr
```
