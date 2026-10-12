---
title: "extract"
description: "yosoi.contracts.extract Python API reference."
order: 0
---

`yosoi.contracts.extract`

```python
def extract[T: 'Contract'](document: Document | BoundDocument | ParsedDocument, contract: type[T]) -> Extracted[T]:
```

Locate pinned fields and return Rust's extraction outcome.

[Source: python/yosoi/contracts.py:978](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/contracts.py#L978-L982)
