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

[Source: python/yosoi/outcomes.py:997](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/outcomes.py#L997-L1007)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['no_match']
document_id: DocumentId
```
