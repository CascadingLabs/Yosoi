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

[Source: python/yosoi/browser.py:275](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L275-L291)

## Base classes

[WaitExpectation](/yosoi/python-api/browser/types/wait-expectation/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['condition'] = 'condition'
condition: Condition
```
