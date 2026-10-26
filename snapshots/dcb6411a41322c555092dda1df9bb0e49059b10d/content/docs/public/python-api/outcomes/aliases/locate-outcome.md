---
title: "LocateOutcome"
description: "yosoi.outcomes.LocateOutcome Python API reference."
order: 0
---

`yosoi.outcomes.LocateOutcome`

```python
LocateOutcome = Annotated[Matched | NoMatch | Indeterminate | LocateFailed, Field(discriminator='status')]
```

Tagged matches, complete no-match, indeterminate evidence, or typed failure. An
empty convenience list alone cannot distinguish these states.

[Source: python/yosoi/outcomes.py:1038](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/outcomes.py#L1038-L1041)
