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

[Source: python/yosoi/browser.py:208](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L208-L219)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['wait'] = 'wait'
milliseconds: U64
```
