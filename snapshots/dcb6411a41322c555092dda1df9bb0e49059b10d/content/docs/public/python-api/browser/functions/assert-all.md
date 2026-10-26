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

Python validation failures retain Rust-compatible field issues in the assertion
report. Sanitized Pydantic details are carried as a tagged item in
``extraction_diagnostics`` because the Rust FieldIssue wire shape is fixed.

[Source: python/yosoi/browser.py:2038](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L2038-L2075)
