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

[Source: python/yosoi/outcomes.py:997](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/outcomes.py#L997-L1007)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['no_match']
document_id: DocumentId
```
