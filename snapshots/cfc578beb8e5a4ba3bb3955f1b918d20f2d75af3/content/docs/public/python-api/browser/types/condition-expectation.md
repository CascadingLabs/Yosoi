---
title: "ConditionExpectation"
description: "yosoi.browser.ConditionExpectation Python API reference."
order: 0
---

`yosoi.browser.ConditionExpectation`

```python
class ConditionExpectation(WaitExpectation):
```

Observe a DOM condition as part of an Until wait.

Attributes:
    kind: Wire discriminator identifying this declaration.
    condition: Existence, visibility, or minimum-count condition; selector is
        bounded to 4,096 UTF-8 bytes.

[Source: python/yosoi/browser.py:272](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L272-L288)

## Base classes

[WaitExpectation](/yosoi/python-api/browser/types/wait-expectation/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['condition'] = 'condition'
condition: Condition
```
