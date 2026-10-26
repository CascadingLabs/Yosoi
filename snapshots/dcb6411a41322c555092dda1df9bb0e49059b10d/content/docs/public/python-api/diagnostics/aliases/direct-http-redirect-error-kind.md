---
title: "DirectHttpRedirectErrorKind"
description: "yosoi.diagnostics.DirectHttpRedirectErrorKind Python API reference."
order: 0
---

`yosoi.diagnostics.DirectHttpRedirectErrorKind`

```python
DirectHttpRedirectErrorKind = Literal['missing_location', 'malformed_location', 'credentials_not_allowed', 'unsupported_scheme', 'target_refused', 'loop', 'hop_limit']
```

Redirect rejection reason; rejected targets are not followed successfully.

[Source: python/yosoi/diagnostics.py:53](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/diagnostics.py#L53-L61)
