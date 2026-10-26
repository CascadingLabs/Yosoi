---
title: "Wait"
description: "yosoi.browser.Wait Python API reference."
order: 0
---

`yosoi.browser.Wait`

```python
class Wait(ImmutableModel):
```

Declare an explicit elapsed-time wait.

Elapsed time is not evidence that a page or operation is ready.

Attributes:
    kind: Wire discriminator identifying this declaration.
    milliseconds: Unsigned duration in milliseconds; zero is permitted.

[Source: python/yosoi/browser.py:205](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L205-L216)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['wait'] = 'wait'
milliseconds: U64
```
