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

[Source: python/yosoi/diagnostics.py:185](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/diagnostics.py#L185-L187)
