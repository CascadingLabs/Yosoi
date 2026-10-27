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

[Source: python/yosoi/browser.py:194](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L194-L205)

## Base classes

[TriggerStep](/yosoi/python-api/browser/types/trigger-step/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['enter_text'] = 'enter_text'
selector: StrictStr = Field(min_length=1, max_length=4096)
text: StrictStr
```
