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

[Source: python/yosoi/request.py:159](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/request.py#L159-L162)
