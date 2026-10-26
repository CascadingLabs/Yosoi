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

[Source: python/yosoi/archive.py:151](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/archive.py#L151-L293)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, handle: _native.Archive) -> None:
```

Wrap a native handle; applications should use Archive.open.

[Source: python/yosoi/archive.py:160](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/archive.py#L160-L162)

### open

```python
@classmethod
async def open(cls, root: str | PathLike[str]) -> Self:
```

Open or create an Archive root with private filesystem permissions.

Raises:
    ArchiveError: Platform, path safety, permissions or filesystem I/O fails.

[Source: python/yosoi/archive.py:165](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/archive.py#L165-L174)

### root

```python
@property
def root(self) -> Path:
```

Return the canonical absolute root without opening a file.

[Source: python/yosoi/archive.py:177](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/archive.py#L177-L179)

### write

```python
async def write(self, value: Document) -> DocumentArchiveRef:
```



[Source: python/yosoi/archive.py:182](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/archive.py#L182-L182)

### write

```python
async def write(self, value: Plan) -> PlanArchiveRef:
```



[Source: python/yosoi/archive.py:185](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/archive.py#L185-L185)

### write

```python
async def write(self, value: AutomationRecord) -> AutomationRecordRef:
```



[Source: python/yosoi/archive.py:188](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/archive.py#L188-L188)

### write

```python
async def write(self, value: Outcome) -> OutcomeRef:
```



[Source: python/yosoi/archive.py:191](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/archive.py#L191-L191)

### write

```python
async def write(self, value: Document | Plan | AutomationRecord | Outcome) -> DocumentArchiveRef | PlanArchiveRef | AutomationRecordRef | OutcomeRef:
```

Save a supported value and return a distinct immutable reference.

Exact bytes, profiles, coordinates and result certainty are retained.
Unsupported application objects raise TypeError. Invalid evidence,
excessive payloads and storage failures raise ArchiveError.

[Source: python/yosoi/archive.py:193](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/archive.py#L193-L221)

### read

```python
async def read(self, reference: DocumentArchiveRef) -> Document:
```



[Source: python/yosoi/archive.py:224](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/archive.py#L224-L224)

### read

```python
async def read(self, reference: PlanArchiveRef) -> Plan:
```



[Source: python/yosoi/archive.py:227](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/archive.py#L227-L227)

### read

```python
async def read(self, reference: AutomationRecordRef) -> AutomationRecord:
```



[Source: python/yosoi/archive.py:230](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/archive.py#L230-L230)

### read

```python
async def read(self, reference: OutcomeRef) -> Outcome:
```



[Source: python/yosoi/archive.py:233](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/archive.py#L233-L233)

### read

```python
async def read(self, reference: DocumentArchiveRef | PlanArchiveRef | AutomationRecordRef | OutcomeRef) -> Document | Plan | AutomationRecord | Outcome:
```

Read exact saved evidence without launching a browser or fetching URLs.

References can be serialized with model_dump_json and reconstructed with
their class's model_validate_json. Missing or corrupt data and unsupported
versions raise ArchiveError. An unsupported reference type raises TypeError.

[Source: python/yosoi/archive.py:235](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/archive.py#L235-L266)

### export_file

```python
async def export_file(self, reference: OutcomeRef, path: str | PathLike[str]) -> None:
```

Export a Surface outcome as one immutable, self-contained file.

The destination must not exist. Atomic publication requires hard links.
A sync error can leave a complete destination; cancellation stops waiting,
while native publication can finish. No unrelated Archive values are copied.

[Source: python/yosoi/archive.py:268](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/archive.py#L268-L281)

### import_file

```python
async def import_file(self, path: str | PathLike[str]) -> OutcomeRef:
```

Validate and import one portable outcome without its original store.

Version, size, digest and outcome checks precede persistence. Corruption
raises ArchiveError. Import restores evidence and never action authority.

[Source: python/yosoi/archive.py:283](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/archive.py#L283-L293)
