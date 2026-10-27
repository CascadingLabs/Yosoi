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

[Source: python/yosoi/browser.py:246](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L246-L257)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['wait_until'] = 'wait_until'
condition: Condition
timeout_ms: PositiveU64
```
