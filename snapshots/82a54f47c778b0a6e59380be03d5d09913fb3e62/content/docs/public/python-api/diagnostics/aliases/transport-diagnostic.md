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

[Source: python/yosoi/diagnostics.py:185](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/diagnostics.py#L185-L187)
