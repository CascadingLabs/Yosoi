---
title: "ResponseExpectation"
description: "yosoi.browser.ResponseExpectation Python API reference."
order: 0
---

`yosoi.browser.ResponseExpectation`

```python
class ResponseExpectation(WaitExpectation):
```

Observe a matching network response during an Until wait.

A matching response is evidence for this expectation, not a general guarantee that
every page request succeeded.

Attributes:
    kind: Wire discriminator identifying this declaration.
    url: Exact full response URL bounded to 8,192 UTF-8 bytes.
    method: Optional HTTP method filter bounded to 32 UTF-8 bytes.
    status: Optional expected HTTP status from 100 through 599.
    json_matches: Up to 32 JSON comparisons; serialized under the key json.

[Source: python/yosoi/browser.py:383](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L383-L416)

## Base classes

[WaitExpectation](/yosoi/python-api/browser/types/wait-expectation/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['response'] = 'response'
url: StrictStr = Field(min_length=1, max_length=8192)
method: StrictStr | None = Field(default=None, max_length=32)
status: HttpStatus | None = None
json_matches: tuple[JsonMatch, ...] = Field(default_factory=tuple, max_length=32, validation_alias='json', serialization_alias='json')
```
