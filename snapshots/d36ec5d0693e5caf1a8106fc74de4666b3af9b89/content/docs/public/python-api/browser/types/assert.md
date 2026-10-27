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

[Source: python/yosoi/browser.py:232](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L232-L243)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['assert'] = 'assert'
condition: Condition
```
