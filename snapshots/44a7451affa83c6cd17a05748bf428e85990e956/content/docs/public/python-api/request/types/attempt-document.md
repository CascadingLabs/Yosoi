---
title: "AttemptDocument"
description: "yosoi.request.AttemptDocument Python API reference."
order: 0
---

`yosoi.request.AttemptDocument`

```python
class AttemptDocument(ImmutableModel):
```

One authored document request and its typed production outcome.

Attributes:
    requested: Requested response, rendered DOM, accessibility, or network
        representation.
    outcome: Produced, partial, unavailable, or unprojectable evidence, without
        collapsing these states.

[Source: python/yosoi/request.py:168](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/request.py#L168-L179)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
requested: DocumentRequest
outcome: DocumentOutcome
```
