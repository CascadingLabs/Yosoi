---
title: "ArchivedContractOutcome"
description: "yosoi.runtime_contracts.ArchivedContractOutcome Python API reference."
order: 0
---

`yosoi.runtime_contracts.ArchivedContractOutcome`

```python
class ArchivedContractOutcome:
```

Inspect a portable Contract outcome without a live Rust handle.

Parsing verifies the archive structure; it does not re-execute extraction or prove
business success. The original JSON is retained unchanged.

Attributes:
    view: Immutable status-tagged DTO parsed from the supplied archive JSON.

[Source: python/yosoi/runtime_contracts.py:405](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L405-L497)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, value: str) -> None:
```

Parse a portable archive and seal its typed view.

Args:
    value: Archive JSON emitted by Rust or a retained portable artifact.

Raises:
    ValueError: JSON is malformed or does not match an archive outcome variant.

[Source: python/yosoi/runtime_contracts.py:417](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L417-L433)

### status

```python
@property
def status(self) -> str:
```

Return the wire status; it does not alone prove business success.

[Source: python/yosoi/runtime_contracts.py:442](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L442-L444)

### document_id

```python
@property
def document_id(self) -> str | None:
```

Return the source document identity when this status carries one.

[Source: python/yosoi/runtime_contracts.py:447](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L447-L449)

### completeness

```python
@property
def completeness(self) -> IncompleteEvidence | None:
```

Return incomplete-evidence details for an indeterminate result, else None.

[Source: python/yosoi/runtime_contracts.py:452](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L452-L454)

### reason_code

```python
@property
def reason_code(self) -> str | None:
```

Return the indeterminate reason code, or None for other statuses.

[Source: python/yosoi/runtime_contracts.py:457](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L457-L459)

### failure

```python
@property
def failure(self) -> Failure | ArchivedExtractionFailure | ArchivedValidationFailure | None:
```

Return the typed phase failure, or None when this status has no failure.

[Source: python/yosoi/runtime_contracts.py:462](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L462-L466)

### records

```python
@property
def records(self) -> tuple[ArchivedValidatedContractRecord, ...]:
```

Return accepted records for evaluated results, otherwise an empty tuple.

[Source: python/yosoi/runtime_contracts.py:469](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L469-L471)

### issues

```python
@property
def issues(self) -> tuple[ArchivedContractRecordIssue, ...]:
```

Return evaluated candidate issues, or an empty tuple otherwise.

[Source: python/yosoi/runtime_contracts.py:474](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L474-L476)

### extraction_diagnostics

```python
@property
def extraction_diagnostics(self) -> tuple[ExtractionDiagnostic, ...]:
```

Return evaluated extraction diagnostics, otherwise an empty tuple.

[Source: python/yosoi/runtime_contracts.py:479](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L479-L485)

### to_json

```python
def to_json(self) -> str:
```

Return the original archive JSON unchanged.

[Source: python/yosoi/runtime_contracts.py:487](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L487-L489)

### model_dump

```python
def model_dump(self) -> dict[str, Any]:
```

Decode the original wire into a new dictionary.

[Source: python/yosoi/runtime_contracts.py:491](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L491-L493)

### model_dump_json

```python
def model_dump_json(self) -> str:
```

Return the original archive JSON unchanged.

[Source: python/yosoi/runtime_contracts.py:495](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L495-L497)
