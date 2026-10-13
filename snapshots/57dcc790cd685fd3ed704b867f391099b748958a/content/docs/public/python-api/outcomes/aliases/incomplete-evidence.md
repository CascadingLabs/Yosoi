---
title: "IncompleteEvidence"
description: "yosoi.outcomes.IncompleteEvidence Python API reference."
order: 0
---

`yosoi.outcomes.IncompleteEvidence`

```python
IncompleteEvidence = Annotated[Partial | Unknown, Field(discriminator='status')]
```

Partial or unknown evidence that cannot establish complete absence. Known loss and
unestablished coverage remain distinct.

[Source: python/yosoi/outcomes.py:562](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/outcomes.py#L562-L562)
