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

[Source: python/yosoi/browser.py:1939](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L1939-L1976)
