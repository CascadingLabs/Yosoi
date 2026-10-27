---
title: "rerun_browser"
description: "yosoi.surface.rerun_browser Python API reference."
order: 0
---

`yosoi.surface.rerun_browser`

```python
async def rerun_browser(outcome: Outcome, policy: SurfacePolicy, count: int=1, headless: bool=True) -> tuple[Outcome, ...]:
```

Rerun a sealed browser recipe with explicit source display selection.

Each iteration resolves fresh references and retains its own outcome.
Errors preserve partial evidence; they never imply rollback of dispatched effects.

[Source: python/yosoi/surface.py:1190](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L1190-L1207)
