---
title: "CountAtLeast"
description: "yosoi.browser.CountAtLeast Python API reference."
order: 0
---

`yosoi.browser.CountAtLeast`

```python
class CountAtLeast(ImmutableModel):
```

Declare a minimum number of matching DOM elements.

Attributes:
    kind: Wire discriminator identifying this declaration.
    selector: CSS selector identifying elements on the current browser page.
    count: Unsigned minimum match count; zero is permitted.

[Source: python/yosoi/browser.py:121](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L121-L132)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['count_at_least'] = 'count_at_least'
selector: StrictStr = Field(min_length=1, max_length=4096)
count: U64
```
