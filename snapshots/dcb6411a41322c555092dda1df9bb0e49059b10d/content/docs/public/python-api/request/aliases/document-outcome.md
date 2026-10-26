---
title: "DocumentOutcome"
description: "yosoi.request.DocumentOutcome Python API reference."
order: 0
---

`yosoi.request.DocumentOutcome`

```python
DocumentOutcome = Annotated[Produced | PartialDocument | Unavailable | Unprojectable, Field(discriminator='status')]
```

Tagged document production states. Produced, partial, unavailable, and unprojectable
retain distinct evidence and absence meanings.

[Source: python/yosoi/request.py:159](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/request.py#L159-L162)
