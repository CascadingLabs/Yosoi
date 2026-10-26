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

[Source: python/yosoi/search.py:456](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/search.py#L456-L458)
