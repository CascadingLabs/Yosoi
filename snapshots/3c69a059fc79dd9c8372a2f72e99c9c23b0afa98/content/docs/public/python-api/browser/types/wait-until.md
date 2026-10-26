---
title: "WaitUntil"
description: "yosoi.browser.WaitUntil Python API reference."
order: 0
---

`yosoi.browser.WaitUntil`

```python
class WaitUntil(ImmutableModel):
```

Declare a bounded wait for a DOM condition.

Attributes:
    kind: Wire discriminator identifying this declaration.
    condition: Existence, visibility, or minimum-count condition to observe.
    timeout_ms: Positive local deadline in milliseconds.

[Source: python/yosoi/browser.py:243](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L243-L254)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['wait_until'] = 'wait_until'
condition: Condition
timeout_ms: PositiveU64
```
