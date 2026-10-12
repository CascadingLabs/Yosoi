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

[Source: python/yosoi/browser.py:1884](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L1884-L1916)
