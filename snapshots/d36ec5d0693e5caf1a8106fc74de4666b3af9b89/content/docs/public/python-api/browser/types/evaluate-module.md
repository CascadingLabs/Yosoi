---
title: "EvaluateModule"
description: "yosoi.browser.EvaluateModule Python API reference."
order: 0
---

`yosoi.browser.EvaluateModule`

```python
class EvaluateModule(TriggerStep):
```

Retain a construction-time local JavaScript module graph.

Execution uses the retained local graph and requires JavaScript permission.
Inspection records cannot authorize execution by themselves.

Attributes:
    kind: Wire discriminator identifying this declaration.
    bundle: Rust-validated module bundle bounded to 4 MiB of encoded JSON.

[Source: python/yosoi/browser.py:595](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L595-L612)

## Base classes

[TriggerStep](/yosoi/python-api/browser/types/trigger-step/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['evaluate_module'] = 'evaluate_module'
bundle: dict[str, Any]
```
