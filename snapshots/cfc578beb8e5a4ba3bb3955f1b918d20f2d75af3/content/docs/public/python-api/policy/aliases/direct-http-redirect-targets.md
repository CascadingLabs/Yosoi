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

[Source: python/yosoi/policy.py:60](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L60-L60)
