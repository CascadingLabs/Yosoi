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

[Source: python/yosoi/policy.py:1100](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L1100-L1100)
