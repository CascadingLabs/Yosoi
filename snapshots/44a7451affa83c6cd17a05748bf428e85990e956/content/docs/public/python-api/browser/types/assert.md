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

[Source: python/yosoi/browser.py:232](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L232-L243)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['assert'] = 'assert'
condition: Condition
```
