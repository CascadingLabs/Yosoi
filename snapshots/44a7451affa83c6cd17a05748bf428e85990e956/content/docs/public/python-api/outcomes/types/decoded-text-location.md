---
title: "DecodedTextLocation"
description: "yosoi.outcomes.DecodedTextLocation Python API reference."
order: 0
---

`yosoi.outcomes.DecodedTextLocation`

```python
class DecodedTextLocation(ImmutableModel):
```

Tagged byte and Unicode-scalar evidence for a decoded-text match.

Attributes:
    kind: Discriminator fixed to decoded_text for tagged decoding.
    coordinate: Paired ranges supplied for the same retained match.

[Source: python/yosoi/outcomes.py:453](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/outcomes.py#L453-L462)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['decoded_text']
coordinate: DecodedTextCoordinate
```
