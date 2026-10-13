---
title: "TransportDiagnostic"
description: "yosoi.diagnostics.TransportDiagnostic Python API reference."
order: 0
---

`yosoi.diagnostics.TransportDiagnostic`

```python
type TransportDiagnostic = Annotated[_DirectHttpTransportUnit | _DirectHttpRedirect, Field(discriminator='kind')]
```

Direct HTTP transport failure or typed redirect rejection details.

[Source: python/yosoi/diagnostics.py:185](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/diagnostics.py#L185-L187)
