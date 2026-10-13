---
title: "yosoi.contracts"
description: "Public declarations in yosoi.contracts."
order: 0
---

`yosoi.contracts`

Declarative Contracts over Rust's extraction and validation pipeline.

[Source: python/yosoi/contracts.py:1](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L1-L1)

## Types

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

## Functions

| Name | Summary |
| --- | --- |
| [`Field`](/yosoi/python-api/contracts/functions/field/) | Describe a Contract field using a genuine Pydantic FieldInfo. |
| [`extract`](/yosoi/python-api/contracts/functions/extract/) | Locate pinned fields and return Rust's extraction outcome. |
| [`value_type_id`](/yosoi/python-api/contracts/functions/value-type-id/) | Return the Rust ContractValue identity declared by a scalar type. |

## Aliases

| Name | Summary |
| --- | --- |
| [`ArchivedContractCandidateField`](/yosoi/python-api/contracts/aliases/archived-contract-candidate-field/) | Store portable evidence for one archived candidate field. |
| [`ArchivedContractField`](/yosoi/python-api/contracts/aliases/archived-contract-field/) | Pair an archived schema field ID with its accepted value. |
| [`ArchivedContractMoneyUsd`](/yosoi/python-api/contracts/aliases/archived-contract-money-usd/) | Store USD money as a portable signed minor-unit amount. |
| [`ArchivedContractOutcome`](/yosoi/python-api/contracts/aliases/archived-contract-outcome/) | Inspect a portable Contract outcome without a live Rust handle. |
| [`ArchivedContractRecordIssue`](/yosoi/python-api/contracts/aliases/archived-contract-record-issue/) | Retain a rejected portable candidate with its field issues. |
| [`ArchivedContractString`](/yosoi/python-api/contracts/aliases/archived-contract-string/) | Store a validated string in the portable archive format. |
| [`ArchivedContractValue`](/yosoi/python-api/contracts/aliases/archived-contract-value/) | Portable string or signed USD minor-unit value tagged by type. |
| [`ArchivedValidatedContractRecord`](/yosoi/python-api/contracts/aliases/archived-validated-contract-record/) | Retain accepted portable values together with source evidence. |
| [`Cardinality`](/yosoi/python-api/contracts/aliases/cardinality/) | Required accepted field count: exactly one, zero or one, or an ordered collection including empty. Rust validation enforces these distinctions after extraction. |
| [`ContractSchemaFailure`](/yosoi/python-api/contracts/aliases/contract-schema-failure/) | Structured Rust schema error tagged by its variant and typed details. |
| [`Limit`](/yosoi/python-api/contracts/aliases/limit/) | Strict nonnegative u64 extraction or validation counter. Zero is a finite budget, not an implicit unlimited setting. |
| [`RuntimeCandidate`](/yosoi/python-api/contracts/aliases/runtime-candidate/) | Retain raw findings for every field of one runtime candidate. |
| [`RuntimeContract`](/yosoi/python-api/contracts/aliases/runtime-contract/) | Author a Contract schema for extraction and validation in Rust. |
| [`RuntimeContractOutcome`](/yosoi/python-api/contracts/aliases/runtime-contract-outcome/) | Inspect runtime validation results while retaining the Rust handle. |
| [`RuntimeExactlyOne`](/yosoi/python-api/contracts/aliases/runtime-exactly-one/) | Carry the single value accepted for a required field. |
| [`RuntimeExtracted`](/yosoi/python-api/contracts/aliases/runtime-extracted/) | Inspect runtime extraction results while retaining the Rust handle. |
| [`RuntimeExtractionFailure`](/yosoi/python-api/contracts/aliases/runtime-extraction-failure/) | Typed schema, counting, grouping, or extraction-budget rejection. |
| [`RuntimeFieldValue`](/yosoi/python-api/contracts/aliases/runtime-field-value/) | Validated runtime field value tagged by its declared cardinality. |
| [`RuntimeMany`](/yosoi/python-api/contracts/aliases/runtime-many/) | Carry all accepted values for a repeated field. |
| [`RuntimeMoneyUsd`](/yosoi/python-api/contracts/aliases/runtime-money-usd/) | Carry a USD amount accepted by runtime Contract validation. |
| [`RuntimeRecordIssue`](/yosoi/python-api/contracts/aliases/runtime-record-issue/) | Retain a rejected candidate and its field validation issues. |
| [`RuntimeString`](/yosoi/python-api/contracts/aliases/runtime-string/) | Carry a string accepted by runtime Contract validation. |
| [`RuntimeValidatedRecord`](/yosoi/python-api/contracts/aliases/runtime-validated-record/) | Pair accepted field values with their original candidate evidence. |
| [`RuntimeValidationFailure`](/yosoi/python-api/contracts/aliases/runtime-validation-failure/) | Typed schema, counting, or validation-budget rejection. |
| [`RuntimeValue`](/yosoi/python-api/contracts/aliases/runtime-value/) | String or USD Money value tagged by its runtime wire type. |
| [`RuntimeZeroOrOne`](/yosoi/python-api/contracts/aliases/runtime-zero-or-one/) | Carry an optional field after cardinality and conversion checks. |
