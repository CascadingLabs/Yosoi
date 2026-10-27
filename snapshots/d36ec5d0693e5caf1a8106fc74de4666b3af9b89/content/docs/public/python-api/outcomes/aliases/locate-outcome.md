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

[Source: python/yosoi/outcomes.py:1038](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/outcomes.py#L1038-L1041)
