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

[Source: python/yosoi/search.py:456](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/search.py#L456-L458)
