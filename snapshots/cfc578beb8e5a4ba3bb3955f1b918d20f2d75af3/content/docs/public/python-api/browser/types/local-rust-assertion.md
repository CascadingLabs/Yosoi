---
title: "LocalRustAssertion"
description: "yosoi.browser.LocalRustAssertion Python API reference."
order: 0
---

`yosoi.browser.LocalRustAssertion`

```python
class LocalRustAssertion(ImmutableModel):
```

Retain a local Contract assertion descriptor for inspection.

Executing it requires the original local predicates. Deserialization retains
inspection data but cannot restore executable callback bindings.

Attributes:
    kind: Wire discriminator identifying this declaration.
    assertion: Serialized schema, plan, and named-check declaration.

[Source: python/yosoi/browser.py:538](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L538-L569)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['assert_all'] = 'assert_all'
assertion: dict[str, Any]
```

## Methods

### until

```python
def until(self, *, trigger: Step | None=None) -> UntilStep:
```

Observe these locally bound Contract checks during an Until wait.

Args:
    trigger: Optional supported one-shot action dispatched after registration.

Returns:
    Until declaration retaining the original local predicate binding.

[Source: python/yosoi/browser.py:559](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L559-L569)
