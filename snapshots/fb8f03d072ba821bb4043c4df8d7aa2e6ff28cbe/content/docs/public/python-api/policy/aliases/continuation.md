---
title: "Continuation"
description: "yosoi.policy.Continuation Python API reference."
order: 0
---

`yosoi.policy.Continuation`

```python
Continuation = Annotated[Continue | Stop, Field(discriminator='kind')]
```

Tagged Continue or Stop behavior for known failures and observed cancellations.
Retaining a result does not imply successful business effects.

[Source: python/yosoi/policy.py:1100](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L1100-L1100)
