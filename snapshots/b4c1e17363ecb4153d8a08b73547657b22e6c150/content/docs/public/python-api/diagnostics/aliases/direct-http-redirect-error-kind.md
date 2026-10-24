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

[Source: python/yosoi/diagnostics.py:53](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/diagnostics.py#L53-L61)
