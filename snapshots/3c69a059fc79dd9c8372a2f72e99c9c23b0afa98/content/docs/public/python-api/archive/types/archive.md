---
title: "Archive"
description: "yosoi.archive.Archive Python API reference."
order: 0
---

`yosoi.archive.Archive`

```python
class Archive:
```

Local Unix Archive handle with no open files between operations.

Use ``await Archive.open(path)``. No close method is needed: each asynchronous
read or write owns its filesystem resources. Cancelling an await stops waiting;
the Rust operation still settles, and a write may already have committed.
A cancelled write returns no reference and can leave unreferenced data.

[Source: python/yosoi/archive.py:147](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/archive.py#L147-L239)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, handle: _native.Archive) -> None:
```

Wrap a native handle; applications should use Archive.open.

[Source: python/yosoi/archive.py:156](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/archive.py#L156-L158)

### open

```python
@classmethod
async def open(cls, root: str | PathLike[str]) -> Self:
```

Open or create an Archive root with private filesystem permissions.

Raises:
    ArchiveError: Platform, path safety, permissions or filesystem I/O fails.

[Source: python/yosoi/archive.py:161](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/archive.py#L161-L170)

### root

```python
@property
def root(self) -> Path:
```

Return the canonical absolute root without opening a file.

[Source: python/yosoi/archive.py:173](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/archive.py#L173-L175)

### write

```python
async def write(self, value: Document) -> DocumentArchiveRef:
```



[Source: python/yosoi/archive.py:178](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/archive.py#L178-L178)

### write

```python
async def write(self, value: Plan) -> PlanArchiveRef:
```



[Source: python/yosoi/archive.py:181](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/archive.py#L181-L181)

### write

```python
async def write(self, value: AutomationRecord) -> AutomationRecordRef:
```



[Source: python/yosoi/archive.py:184](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/archive.py#L184-L184)

### write

```python
async def write(self, value: Document | Plan | AutomationRecord) -> DocumentArchiveRef | PlanArchiveRef | AutomationRecordRef:
```

Save a supported value and return a distinct immutable reference.

Exact bytes, profiles, coordinates and result certainty are retained.
Unsupported application objects raise TypeError. Invalid evidence,
excessive payloads and storage failures raise ArchiveError.

[Source: python/yosoi/archive.py:186](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/archive.py#L186-L206)

### read

```python
async def read(self, reference: DocumentArchiveRef) -> Document:
```



[Source: python/yosoi/archive.py:209](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/archive.py#L209-L209)

### read

```python
async def read(self, reference: PlanArchiveRef) -> Plan:
```



[Source: python/yosoi/archive.py:212](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/archive.py#L212-L212)

### read

```python
async def read(self, reference: AutomationRecordRef) -> AutomationRecord:
```



[Source: python/yosoi/archive.py:215](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/archive.py#L215-L215)

### read

```python
async def read(self, reference: DocumentArchiveRef | PlanArchiveRef | AutomationRecordRef) -> Document | Plan | AutomationRecord:
```

Read exact saved evidence without launching a browser or fetching URLs.

References can be serialized with model_dump_json and reconstructed with
their class's model_validate_json. Missing or corrupt data and unsupported
versions raise ArchiveError. An unsupported reference type raises TypeError.

[Source: python/yosoi/archive.py:217](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/archive.py#L217-L239)
