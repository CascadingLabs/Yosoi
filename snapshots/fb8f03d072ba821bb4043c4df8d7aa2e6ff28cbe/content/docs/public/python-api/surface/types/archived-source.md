---
title: "ArchivedSource"
description: "yosoi.surface.ArchivedSource Python API reference."
order: 0
---

`yosoi.surface.ArchivedSource`

```python
class ArchivedSource(ImmutableModel):
```

Exact source bytes and interpretation, independent of a source file path.

[Source: python/yosoi/surface.py:926](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L926-L973)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
key: StrictStr = Field(description='Unique outcome-local source key.')
document: DocumentId = Field(description='Original SDK document identity.')
profile: DocumentProfile = Field(description='Exact document profile and epoch.')
sha256: StrictStr = Field(description='SHA-256 of decoded original bytes.')
content_base64: StrictStr = Field(description='Retained original bytes as base64.')
surface: StrictStr | None = Field(default=None, description='Prepared identity; absent for raw evidence envelopes.')
interpretation: SourceInterpretation = Field(default_factory=SourceInterpretation, description='Interpreter used for restoring this source.')
```

## Methods

### from_document

```python
@classmethod
def from_document(cls, key: str, document: Document, surface: Surface | None=None) -> Self:
```

Freeze exact document bytes and optionally bind a prepared interpretation.

[Source: python/yosoi/surface.py:944](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L944-L952)

### capture

```python
@classmethod
def capture(cls, key: str, surface: Surface) -> Self:
```

Retain a prepared document, image or bundle with its exact identity.

[Source: python/yosoi/surface.py:955](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L955-L959)

### restore

```python
def restore(self, maximum: int=64 * 1024 * 1024) -> Document:
```

Verify and restore original bytes within a byte limit, without source I/O.

[Source: python/yosoi/surface.py:961](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L961-L965)

### restore_surface

```python
def restore_surface(self, limits: Limits | None=None) -> Surface:
```

Restore immutable evidence and reject an interpretation identity mismatch.

[Source: python/yosoi/surface.py:967](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L967-L973)
