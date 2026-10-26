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

[Source: python/yosoi/browser.py:572](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L572-L589)

## Base classes

[TriggerStep](/yosoi/python-api/browser/types/trigger-step/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['evaluate_file'] = 'evaluate_file'
snapshot: dict[str, Any]
```
