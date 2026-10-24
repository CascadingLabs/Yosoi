---
title: "Assert"
description: "yosoi.browser.Assert Python API reference."
order: 0
---

`yosoi.browser.Assert`

```python
class Assert(ImmutableModel):
```

Declare an immediate DOM condition check.

This checks one observation rather than waiting for the condition to become true.

Attributes:
    kind: Wire discriminator identifying this declaration.
    condition: Existence, visibility, or minimum-count condition to evaluate.

[Source: python/yosoi/browser.py:229](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L229-L240)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['assert'] = 'assert'
condition: Condition
```
