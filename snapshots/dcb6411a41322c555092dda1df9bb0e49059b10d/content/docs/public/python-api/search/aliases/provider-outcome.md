---
title: "ProviderOutcome"
description: "yosoi.search.ProviderOutcome Python API reference."
order: 0
---

`yosoi.search.ProviderOutcome`

```python
ProviderOutcome = Annotated[Results | Empty | Failed | Cancelled | NotStarted, Field(discriminator='status')]
```

Tagged provider result distinguishing usable results, empty response, failure,
observed cancellation, and work that never started.

[Source: python/yosoi/search.py:456](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/search.py#L456-L458)
