---
title: "enter_text"
description: "yosoi.browser.enter_text Python API reference."
order: 0
---

`yosoi.browser.enter_text`

```python
def enter_text(selector: str, text: str) -> EnterText:
```

Declare a text input action without executing it.

Args:
    selector: CSS selector for the current browser page.
    text: Text to send, including an empty string.

Returns:
    Immutable EnterText trigger.

[Source: python/yosoi/browser.py:1547](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L1547-L1557)
