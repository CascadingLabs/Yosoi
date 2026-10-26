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

[Source: python/yosoi/policy.py:72](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L72-L72)
