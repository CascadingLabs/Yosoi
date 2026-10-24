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

[Source: python/yosoi/outcomes.py:1038](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/outcomes.py#L1038-L1041)
