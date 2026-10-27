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

[Source: python/yosoi/diagnostics.py:53](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/diagnostics.py#L53-L61)
