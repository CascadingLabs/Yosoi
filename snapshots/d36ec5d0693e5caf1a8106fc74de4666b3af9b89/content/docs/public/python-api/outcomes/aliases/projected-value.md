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

[Source: python/yosoi/outcomes.py:679](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/outcomes.py#L679-L682)
