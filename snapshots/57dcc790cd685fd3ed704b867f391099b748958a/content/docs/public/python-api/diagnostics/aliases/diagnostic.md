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

[Source: python/yosoi/diagnostics.py:217](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/diagnostics.py#L217-L220)
