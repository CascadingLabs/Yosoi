---
title: "replay"
description: "yosoi.surface.replay Python API reference."
order: 0
---

`yosoi.surface.replay`

```python
async def replay(path: str | Path, repeat: int=1, query: str | None=None, output: str | Path | None=None) -> dict[str, object]:
```

Reconstruct a saved handle or portable file without live source processes.

Materialized video pixels need no decoder. Incomplete outcomes are rejected.

[Source: python/yosoi/surface.py:1210](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L1210-L1226)
