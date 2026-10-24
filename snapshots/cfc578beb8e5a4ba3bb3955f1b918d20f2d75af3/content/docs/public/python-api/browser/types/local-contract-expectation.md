---
title: "LocalContractExpectation"
description: "yosoi.browser.LocalContractExpectation Python API reference."
order: 0
---

`yosoi.browser.LocalContractExpectation`

```python
class LocalContractExpectation(WaitExpectation):
```

Retain an inspectable descriptor for local Contract checks.

Executing checks requires the original local predicate binding. Deserializing the
descriptor does not restore executable predicates.

Attributes:
    kind: Wire discriminator identifying this declaration.
    assertion: JSON descriptor bounded to 65,536 encoded bytes.

[Source: python/yosoi/browser.py:291](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L291-L316)

## Base classes

[WaitExpectation](/yosoi/python-api/browser/types/wait-expectation/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['contract'] = 'contract'
assertion: dict[str, Any]
```
