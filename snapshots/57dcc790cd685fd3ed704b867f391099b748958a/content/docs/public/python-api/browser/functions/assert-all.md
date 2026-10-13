---
title: "assert_all"
description: "yosoi.browser.assert_all Python API reference."
order: 0
---

`yosoi.browser.assert_all`

```python
def assert_all(contract: type[Any], *, plan: Plan | None=None, checks: Iterable[Check]) -> LocalRustAssertion:
```

Check one typed Contract observation using synchronous local predicates.

[Source: python/yosoi/browser.py:1884](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/browser.py#L1884-L1916)
