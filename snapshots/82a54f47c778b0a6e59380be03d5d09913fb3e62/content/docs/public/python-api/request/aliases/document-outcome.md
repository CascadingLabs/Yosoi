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

[Source: python/yosoi/request.py:159](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/request.py#L159-L162)
