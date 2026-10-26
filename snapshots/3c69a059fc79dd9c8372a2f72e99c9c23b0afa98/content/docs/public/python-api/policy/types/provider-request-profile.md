---
title: "ProviderRequestProfile"
description: "yosoi.policy.ProviderRequestProfile Python API reference."
order: 0
---

`yosoi.policy.ProviderRequestProfile`

```python
class ProviderRequestProfile(Model):
```

Complete child-request policy sections for a search provider.

Attributes:
    page: Provider-specific acquisitions and document selections.
    request: Provider acquisition deadlines, byte/resource limits, and redirect
        behavior.
    documents: Provider retained-document parsing limits.

[Source: python/yosoi/policy.py:570](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L570-L582)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
page: Page = Field(default_factory=Page)
request: Request = Field(default_factory=Request)
documents: Documents = Field(default_factory=Documents)
```
