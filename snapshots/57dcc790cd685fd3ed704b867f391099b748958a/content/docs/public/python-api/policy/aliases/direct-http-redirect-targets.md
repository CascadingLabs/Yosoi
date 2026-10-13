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

[Source: python/yosoi/policy.py:60](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L60-L60)
