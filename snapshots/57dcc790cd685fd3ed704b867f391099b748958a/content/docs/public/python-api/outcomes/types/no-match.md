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

[Source: python/yosoi/outcomes.py:997](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/outcomes.py#L997-L1007)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['no_match']
document_id: DocumentId
```
