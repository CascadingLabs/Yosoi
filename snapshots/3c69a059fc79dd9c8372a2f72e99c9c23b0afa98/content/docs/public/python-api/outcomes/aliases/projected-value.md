---
title: "ProjectedValue"
description: "yosoi.outcomes.ProjectedValue Python API reference."
order: 0
---

`yosoi.outcomes.ProjectedValue`

```python
ProjectedValue = Annotated[TextValue | TextWithCaptures | AttributeValue | JsonValueProjection | NodeValue, Field(discriminator='kind')]
```

Tagged text, captured text, attribute, JSON, or document-bound node value.
Projection identity retains information omitted by convenience value accessors.

[Source: python/yosoi/outcomes.py:679](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/outcomes.py#L679-L682)
