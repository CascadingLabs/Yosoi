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

[Source: python/yosoi/browser.py:275](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L275-L291)

## Base classes

[WaitExpectation](/yosoi/python-api/browser/types/wait-expectation/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['condition'] = 'condition'
condition: Condition
```
