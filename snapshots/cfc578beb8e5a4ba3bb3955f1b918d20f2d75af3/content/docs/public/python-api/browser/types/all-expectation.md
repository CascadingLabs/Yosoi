---
title: "AllExpectation"
description: "yosoi.browser.AllExpectation Python API reference."
order: 0
---

`yosoi.browser.AllExpectation`

```python
class AllExpectation(WaitExpectation):
```

Require every child expectation within one Until wait.

Attributes:
    kind: Wire discriminator identifying this declaration.
    expectations: One through 128 expectations; complete trees allow at most 128
        nodes and eight nesting levels.

[Source: python/yosoi/browser.py:416](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L416-L426)

## Base classes

[WaitExpectation](/yosoi/python-api/browser/types/wait-expectation/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['all'] = 'all'
expectations: tuple[UntilExpectation, ...] = Field(min_length=1, max_length=128)
```
