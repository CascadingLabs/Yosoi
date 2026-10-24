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

[Source: python/yosoi/outcomes.py:562](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/outcomes.py#L562-L562)
