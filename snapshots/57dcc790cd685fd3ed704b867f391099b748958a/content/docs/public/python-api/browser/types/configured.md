---
title: "Configured"
description: "yosoi.browser.Configured Python API reference."
order: 0
---

`yosoi.browser.Configured`

```python
class Configured(ImmutableModel):
```

Override continuation decisions for one action.

A persisted descriptor does not recreate live cancellation token authority.

Attributes:
    kind: Wire discriminator identifying this declaration.
    action: Action to execute with these overrides.
    on_failure: Failure continuation override; None inherits enclosing defaults.
    on_cancellation: Cancellation continuation override; None inherits enclosing
        defaults.
    cancellation_binding_required: Whether execution needs an external cancellation
        binding restored.

[Source: python/yosoi/browser.py:504](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/browser.py#L504-L523)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['configured'] = 'configured'
action: Step
on_failure: Continuation | None = None
on_cancellation: Continuation | None = None
cancellation_binding_required: StrictBool = False
```
