---
title: "NoMatch"
description: "yosoi.outcomes.NoMatch Python API reference."
order: 0
---

`yosoi.outcomes.NoMatch`

```python
class NoMatch(_Outcome):
```

Complete locator execution found no match within the requested scope.

Attributes:
    status: Discriminator fixed to no_match for tagged decoding.
    document_id: Document whose complete evidence supports this scope-specific
        absence claim.

[Source: python/yosoi/outcomes.py:997](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/outcomes.py#L997-L1007)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['no_match']
document_id: DocumentId
```
