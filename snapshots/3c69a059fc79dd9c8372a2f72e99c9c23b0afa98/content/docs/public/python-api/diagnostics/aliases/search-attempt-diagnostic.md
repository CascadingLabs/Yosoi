---
title: "SearchAttemptDiagnostic"
description: "yosoi.diagnostics.SearchAttemptDiagnostic Python API reference."
order: 0
---

`yosoi.diagnostics.SearchAttemptDiagnostic`

```python
type SearchAttemptDiagnostic = Literal['missing_execution_context', 'policy_resolution_failed', 'direct_http_transport', 'direct_http_body_failed', 'direct_http_finalization_failed', 'browser_cancelled', 'browser_cancelled_cleanup_failed', 'browser_cleanup_failed', 'browser_capture_failed', 'browser_finalization_failed', 'browser_feature_disabled', 'projection_failed'] | _SearchBrowserFailure
```

Search-attempt phase diagnostic or structured browser failure category.

[Source: python/yosoi/diagnostics.py:241](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/diagnostics.py#L241-L257)
