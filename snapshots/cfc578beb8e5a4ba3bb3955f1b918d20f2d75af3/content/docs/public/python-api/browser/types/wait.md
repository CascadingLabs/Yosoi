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

[Source: python/yosoi/browser.py:205](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L205-L216)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['wait'] = 'wait'
milliseconds: U64
```
