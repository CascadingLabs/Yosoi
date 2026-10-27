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

[Source: python/yosoi/policy.py:582](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L582-L594)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
page: Page = Field(default_factory=Page)
request: Request = Field(default_factory=Request)
documents: Documents = Field(default_factory=Documents)
```
