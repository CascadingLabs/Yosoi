---
title: "EvaluateFile"
description: "yosoi.browser.EvaluateFile Python API reference."
order: 0
---

`yosoi.browser.EvaluateFile`

```python
class EvaluateFile(TriggerStep):
```

Retain a construction-time JavaScript file snapshot.

The factory reads source during construction. Later execution uses the retained
snapshot rather than rereading the file, and requires JavaScript permission.

Attributes:
    kind: Wire discriminator identifying this declaration.
    snapshot: Rust-validated source snapshot bounded to 1 MiB of encoded JSON.

[Source: python/yosoi/browser.py:575](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L575-L592)

## Base classes

[TriggerStep](/yosoi/python-api/browser/types/trigger-step/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['evaluate_file'] = 'evaluate_file'
snapshot: dict[str, Any]
```
