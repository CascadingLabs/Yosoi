---
title: "Completeness"
description: "yosoi.outcomes.Completeness Python API reference."
order: 0
---

`yosoi.outcomes.Completeness`

```python
Completeness = Annotated[Complete | Partial | Unknown, Field(discriminator='status')]
```

Tagged complete, partial, or unknown coverage of requested evidence. Complete
coverage is scoped to the operation, not an exhaustive claim about a site.

[Source: python/yosoi/outcomes.py:558](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/outcomes.py#L558-L558)
