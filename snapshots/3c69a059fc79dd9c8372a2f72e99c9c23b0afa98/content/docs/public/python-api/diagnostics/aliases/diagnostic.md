---
title: "Diagnostic"
description: "yosoi.diagnostics.Diagnostic Python API reference."
order: 0
---

`yosoi.diagnostics.Diagnostic`

```python
type Diagnostic = Annotated[_RequestDiagnosticUnit | _DirectHttpTransportDiagnostic | _BrowserFailureDiagnostic, Field(discriminator='kind')]
```

Request phase failure, transport detail, or browser failure tagged by kind.

[Source: python/yosoi/diagnostics.py:217](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/diagnostics.py#L217-L220)
