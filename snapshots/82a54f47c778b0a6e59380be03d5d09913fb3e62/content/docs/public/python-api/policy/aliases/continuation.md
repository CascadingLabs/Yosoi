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

[Source: python/yosoi/policy.py:1088](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L1088-L1088)
