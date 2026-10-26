---
title: "Types"
description: "Types declared in yosoi.contracts."
order: 0
---

| Name | Summary |
| --- | --- |
| [`Candidate`](/yosoi/python-api/contracts/types/candidate/) | Grouping metadata for generated typed candidate records. |
| [`CandidateField`](/yosoi/python-api/contracts/types/candidate-field/) | Ordered projection values and original findings before conversion. |
| [`Contract`](/yosoi/python-api/contracts/types/contract/) | Mutable Pydantic record model with native candidate extraction. |
| [`ContractIssues`](/yosoi/python-api/contracts/types/contract-issues/) | Structured rejection of a request for all accepted record values. |
| [`ContractOutcome`](/yosoi/python-api/contracts/types/contract-outcome/) | Pydantic validation report retaining accepted and rejected candidates. |
| [`ContractRecordIssue`](/yosoi/python-api/contracts/types/contract-record-issue/) | One rejected candidate with Pydantic details and source evidence. |
| [`ContractSchema`](/yosoi/python-api/contracts/types/contract-schema/) | Native transport meaning, scope, and ordered field declarations. |
| [`ContractValue`](/yosoi/python-api/contracts/types/contract-value/) | Identity-only protocol for native Rust Contract scalar types. |
| [`Extracted`](/yosoi/python-api/contracts/types/extracted/) | Read-only candidate assembly outcome awaiting explicit validation. |
| [`ExtractionDiagnostic`](/yosoi/python-api/contracts/types/extraction-diagnostic/) | Nonfatal finding-lineage mismatch during candidate grouping. |
| [`ExtractionLimits`](/yosoi/python-api/contracts/types/extraction-limits/) | Nonnegative u64 budgets for candidate assembly. |
| [`ExtractionPolicy`](/yosoi/python-api/contracts/types/extraction-policy/) | Immutable acceptance and native-work limits for Python Contract extraction. |
| [`FieldIssue`](/yosoi/python-api/contracts/types/field-issue/) | Rejected Contract field with supporting source-derived evidence. |
| [`FieldIssueKind`](/yosoi/python-api/contracts/types/field-issue-kind/) | Cardinality, completeness, or projection conversion rejection. |
| [`FieldSchema`](/yosoi/python-api/contracts/types/field-schema/) | Native transport field meaning, cardinality, and scalar type metadata. |
| [`RecordIssue`](/yosoi/python-api/contracts/types/record-issue/) | Rejected candidate record with retained field issues. |
| [`TerminalFailure`](/yosoi/python-api/contracts/types/terminal-failure/) | Structured phase rejection facts, distinct from field issues. |
| [`ValidatedRecord`](/yosoi/python-api/contracts/types/validated-record/) | Pydantic-accepted typed value with original candidate evidence retained. |
| [`ValidationLimits`](/yosoi/python-api/contracts/types/validation-limits/) | Native-shaped work budgets applied before Python validation. |
