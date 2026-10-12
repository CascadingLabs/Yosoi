---
title: "Types"
description: "Types declared in yosoi.contracts."
order: 0
---

| Name | Summary |
| --- | --- |
| [`Candidate`](/yosoi/python-api/contracts/types/candidate/) | Grouping metadata for generated typed candidate records. |
| [`CandidateField`](/yosoi/python-api/contracts/types/candidate-field/) | Ordered projection values and original findings before conversion. |
| [`Contract`](/yosoi/python-api/contracts/types/contract/) | Typed record definition with Rust-owned cardinality and validation. |
| [`ContractIssues`](/yosoi/python-api/contracts/types/contract-issues/) | Structured rejection of a request for all accepted record values. |
| [`ContractOutcome`](/yosoi/python-api/contracts/types/contract-outcome/) | Read-only evaluation retaining accepted and rejected candidates. |
| [`ContractSchema`](/yosoi/python-api/contracts/types/contract-schema/) | Portable record meaning, scope, and ordered field declarations. |
| [`ContractValue`](/yosoi/python-api/contracts/types/contract-value/) | Identity-only protocol for the Rust Contract scalar vocabulary. |
| [`Extracted`](/yosoi/python-api/contracts/types/extracted/) | Read-only candidate assembly outcome awaiting explicit validation. |
| [`ExtractionDiagnostic`](/yosoi/python-api/contracts/types/extraction-diagnostic/) | Nonfatal finding-lineage mismatch during candidate grouping. |
| [`ExtractionLimits`](/yosoi/python-api/contracts/types/extraction-limits/) | Nonnegative u64 budgets for candidate assembly. |
| [`FieldIssue`](/yosoi/python-api/contracts/types/field-issue/) | Rejected Contract field with supporting source-derived evidence. |
| [`FieldIssueKind`](/yosoi/python-api/contracts/types/field-issue-kind/) | Cardinality, completeness, conversion, or semantic field rejection. |
| [`FieldSchema`](/yosoi/python-api/contracts/types/field-schema/) | Rust-validated field meaning, cardinality, and type metadata. |
| [`Money`](/yosoi/python-api/contracts/types/money/) | USD monetary scalar represented by integer minor units. |
| [`RecordIssue`](/yosoi/python-api/contracts/types/record-issue/) | Rejected candidate record with retained field issues. |
| [`TerminalFailure`](/yosoi/python-api/contracts/types/terminal-failure/) | Structured phase rejection facts, distinct from field issues. |
| [`ValidatedRecord`](/yosoi/python-api/contracts/types/validated-record/) | Accepted typed value with original candidate evidence retained. |
| [`ValidationLimits`](/yosoi/python-api/contracts/types/validation-limits/) | Rust-owned default budgets for conversion and validation accounting. |
