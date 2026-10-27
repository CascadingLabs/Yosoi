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

[Source: python/yosoi/request.py:159](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/request.py#L159-L162)
