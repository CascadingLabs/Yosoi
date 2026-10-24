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

[Source: python/yosoi/browser.py:592](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L592-L609)

## Base classes

[TriggerStep](/yosoi/python-api/browser/types/trigger-step/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['evaluate_module'] = 'evaluate_module'
bundle: dict[str, Any]
```
