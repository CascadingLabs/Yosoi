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

[Source: python/yosoi/browser.py:1646](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L1646-L1656)
