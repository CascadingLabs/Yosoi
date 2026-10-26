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

[Source: python/yosoi/request.py:159](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/request.py#L159-L162)
