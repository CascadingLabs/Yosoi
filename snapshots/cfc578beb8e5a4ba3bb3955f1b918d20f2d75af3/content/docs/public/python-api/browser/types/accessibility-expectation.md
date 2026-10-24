---
title: "AccessibilityExpectation"
description: "yosoi.browser.AccessibilityExpectation Python API reference."
order: 0
---

`yosoi.browser.AccessibilityExpectation`

```python
class AccessibilityExpectation(WaitExpectation):
```

Observe an accessible name and optional role during Until.

Attributes:
    kind: Wire discriminator identifying this declaration.
    name: Nonblank accessible name bounded to 4,096 UTF-8 bytes.
    role: Optional nonblank accessibility role bounded to 128 UTF-8 bytes.

[Source: python/yosoi/browser.py:319](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L319-L342)

## Base classes

[WaitExpectation](/yosoi/python-api/browser/types/wait-expectation/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['accessibility'] = 'accessibility'
name: StrictStr = Field(min_length=1, max_length=4096)
role: StrictStr | None = None
```
