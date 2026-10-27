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

[Source: python/yosoi/surface.py:1210](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L1210-L1226)
