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

[Source: python/yosoi/outcomes.py:1038](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/outcomes.py#L1038-L1041)
