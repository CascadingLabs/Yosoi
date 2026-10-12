---
title: "DirectHttpRedirectTargets"
description: "yosoi.policy.DirectHttpRedirectTargets Python API reference."
order: 0
---

`yosoi.policy.DirectHttpRedirectTargets`

```python
DirectHttpRedirectTargets = Literal['allow_http_and_https', 'same_origin']
```

Redirect admission allows supported HTTP(S) destinations or restricts transitions
to the seed origin. Hop and request budgets apply separately.

[Source: python/yosoi/policy.py:60](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L60-L60)
