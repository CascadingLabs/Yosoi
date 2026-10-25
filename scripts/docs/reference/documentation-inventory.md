# Public API documentation inventory

Baseline: `6f8c447199361213a4aaf26d0a621cd1fca3e5de` (current main when this work began). Counts below precede documentation edits in this workspace.

## Scope and evidence

- Rust: compiler `missing_docs` diagnostics for `yosoi --lib --features browser`, including reachable definitions in private modules. The compiler reports 1,277 gaps. This profile does not prove coverage of scanner/encoding feature additions or the independently versioned derive crate.
- Python: Ruff D100–D107 reports 527 missing docstrings in `python/yosoi`. Public annotated class fields are inspected separately: 639 candidates lack either an `Attributes:` entry or a direct `Field(description=...)`. This syntactic field inventory includes class configuration annotations and needs semantic review; it is not a Ruff enforcement claim.
- Excluded: private implementation APIs, vendored browser code, and Python native stubs. Rust compiler reachability determines public items; a private directory alone does not exclude a re-exported definition.

## Generator findings

- The verified local Rust reference manifest identifies the same source commit as this baseline. `ResponseTermination` parent prose reaches its generated JSON. Both variant descriptions are empty because the source variants lack comments.
- Rust `model.mjs` preserves `item.docs` and `member.docs`, including enum variants and methods. Compiler-derived trait implementations (for example derived `Clone` and `Debug`) can have empty docs despite needing no new handwritten source documentation. Do not count every empty generated member as a source gap.
- The real compiler fixture now asserts parent, variant, and method comment preservation; it passes locally. Regeneration and inspection of the changed Yosoi pages remain required.
- At the baseline snapshot, no Python API reference extractor or renderer was found. The default workspaces subsequently added `scripts/docs/python_reference.py` and frontend integration as separate in-progress work. That extractor reads declarations and docstrings without importing the native SDK; it is preserved outside this source-documentation revision.
- The existing docs watcher runs from `CascadingLabsFE` and selects the default `Yosoi` checkout. It does not yet serve this isolated API documentation workspace.

## Rust gaps by declaration kind

| Kind | Missing |
| --- | ---: |
| a variant | 540 |
| a struct field | 410 |
| a method | 177 |
| an enum | 50 |
| a struct | 39 |
| an associated function | 38 |
| a function | 16 |
| a constant | 4 |
| a trait | 1 |
| an associated type | 1 |
| an associated constant | 1 |

## Rust files with public gaps

| Source file | Missing | First reported declaration |
| --- | ---: | --- |
| [crates/yosoi/src/action/module/types.rs](../../../crates/yosoi/src/action/module/types.rs) | 19 | `ParseFailed { module_id: String },` (line 153) |
| [crates/yosoi/src/action/source.rs](../../../crates/yosoi/src/action/source.rs) | 12 | `File { path: PathBuf },` (line 157) |
| [crates/yosoi/src/assertions.rs](../../../crates/yosoi/src/assertions.rs) | 43 | `pub const MAX_CHECKS: usize = 128;` (line 24) |
| [crates/yosoi/src/automation_record.rs](../../../crates/yosoi/src/automation_record.rs) | 58 | `pub id: String,` (line 49) |
| [crates/yosoi/src/contracts.rs](../../../crates/yosoi/src/contracts.rs) | 2 | `pub fn new(schema: ContractSchema) -> Result<Self, RuntimeContractError> {` (line 33) |
| [crates/yosoi/src/expect.rs](../../../crates/yosoi/src/expect.rs) | 9 | `Condition { condition: Condition },` (line 22) |
| [crates/yosoi/src/flow/error.rs](../../../crates/yosoi/src/flow/error.rs) | 57 | `pub enum FlowValidationError {` (line 10) |
| [crates/yosoi/src/flow/model.rs](../../../crates/yosoi/src/flow/model.rs) | 33 | `AssertAll { assertion: LocalAssertion },` (line 49) |
| [crates/yosoi/src/internal/contract_validation/issue.rs](../../../crates/yosoi/src/internal/contract_validation/issue.rs) | 37 | `pub enum ValidationCode {` (line 9) |
| [crates/yosoi/src/internal/contract_validation/mod.rs](../../../crates/yosoi/src/internal/contract_validation/mod.rs) | 1 | `fn validate_contract(located: &internal_documents::LocateOutcome) -> ContractOutcome<Self>;` (line 55) |
| [crates/yosoi/src/internal/contract_validation/outcome.rs](../../../crates/yosoi/src/internal/contract_validation/outcome.rs) | 25 | `pub struct ValidatedRecord<T: Contract> {` (line 7) |
| [crates/yosoi/src/internal/contract_validation/runtime.rs](../../../crates/yosoi/src/internal/contract_validation/runtime.rs) | 41 | `pub enum RuntimeContractError {` (line 65) |
| [crates/yosoi/src/internal/contracts/candidate.rs](../../../crates/yosoi/src/internal/contracts/candidate.rs) | 10 | `pub struct CandidateField<T> {` (line 56) |
| [crates/yosoi/src/internal/contracts/ids.rs](../../../crates/yosoi/src/internal/contracts/ids.rs) | 21 | `pub struct $name(String);` (line 9) |
| [crates/yosoi/src/internal/contracts/schema.rs](../../../crates/yosoi/src/internal/contracts/schema.rs) | 24 | `pub enum RecordScope {` (line 12) |
| [crates/yosoi/src/internal/direct_http/error.rs](../../../crates/yosoi/src/internal/direct_http/error.rs) | 11 | `Dns,` (line 16) |
| [crates/yosoi/src/internal/direct_http/redirect.rs](../../../crates/yosoi/src/internal/direct_http/redirect.rs) | 7 | `MissingLocation,` (line 25) |
| [crates/yosoi/src/internal/documents/accessibility/types.rs](../../../crates/yosoi/src/internal/documents/accessibility/types.rs) | 6 | `Complete,` (line 18) |
| [crates/yosoi/src/internal/documents/document.rs](../../../crates/yosoi/src/internal/documents/document.rs) | 6 | `pub fn try_new(value: impl Into<String>) -> Result<Self, DocumentError> {` (line 23) |
| [crates/yosoi/src/internal/documents/document_profile.rs](../../../crates/yosoi/src/internal/documents/document_profile.rs) | 32 | `Source,` (line 10) |
| [crates/yosoi/src/internal/documents/json/types.rs](../../../crates/yosoi/src/internal/documents/json/types.rs) | 4 | `InvalidPointerSyntax,` (line 12) |
| [crates/yosoi/src/internal/documents/limits.rs](../../../crates/yosoi/src/internal/documents/limits.rs) | 10 | `InputBytes,` (line 33) |
| [crates/yosoi/src/internal/documents/locator_declaration.rs](../../../crates/yosoi/src/internal/documents/locator_declaration.rs) | 2 | `pub const fn css(expression: &'static str) -> PinnedLocator {` (line 83) |
| [crates/yosoi/src/internal/documents/outcome.rs](../../../crates/yosoi/src/internal/documents/outcome.rs) | 59 | `Text(String),` (line 25) |
| [crates/yosoi/src/internal/documents/outcome_coordinates.rs](../../../crates/yosoi/src/internal/documents/outcome_coordinates.rs) | 19 | `pub enum CoordinateError {` (line 5) |
| [crates/yosoi/src/internal/documents/outcome_native_coordinates.rs](../../../crates/yosoi/src/internal/documents/outcome_native_coordinates.rs) | 18 | `pub fn try_new(pointer: impl Into<String>) -> Result<Self, CoordinateError> {` (line 13) |
| [crates/yosoi/src/internal/documents/outcome_tree_coordinates.rs](../../../crates/yosoi/src/internal/documents/outcome_tree_coordinates.rs) | 9 | `pub fn try_new(` (line 14) |
| [crates/yosoi/src/internal/documents/plan_authoring.rs](../../../crates/yosoi/src/internal/documents/plan_authoring.rs) | 8 | `pub fn try_new(value: impl Into<String>) -> Result<Self, PlanError> {` (line 23) |
| [crates/yosoi/src/internal/documents/plan_model.rs](../../../crates/yosoi/src/internal/documents/plan_model.rs) | 26 | `pub fn new(outputs: impl IntoIterator<Item = NamedOutput>) -> Result<Self, PlanError> {` (line 138) |
| [crates/yosoi/src/internal/documents/query.rs](../../../crates/yosoi/src/internal/documents/query.rs) | 29 | `Expanded,` (line 32) |
| [crates/yosoi/src/internal/documents/query_builders.rs](../../../crates/yosoi/src/internal/documents/query_builders.rs) | 11 | `pub fn css(value: impl Into<String>) -> Result<QuerySpec, QueryError> {` (line 7) |
| [crates/yosoi/src/internal/documents/query_error.rs](../../../crates/yosoi/src/internal/documents/query_error.rs) | 22 | `pub enum QueryError {` (line 6) |
| [crates/yosoi/src/internal/engine/contract_locator.rs](../../../crates/yosoi/src/internal/engine/contract_locator.rs) | 3 | `pub enum ContractLocatorError {` (line 7) |
| [crates/yosoi/src/internal/engine/document.rs](../../../crates/yosoi/src/internal/engine/document.rs) | 3 | `InvalidResourcePolicy { limit: ResourceLimit },` (line 19) |
| [crates/yosoi/src/internal/engine/execution.rs](../../../crates/yosoi/src/internal/engine/execution.rs) | 14 | `pub enum ExecutionPoolError {` (line 11) |
| [crates/yosoi/src/internal/engine/map/mod.rs](../../../crates/yosoi/src/internal/engine/map/mod.rs) | 4 | `pub struct RequestTrace {` (line 120) |
| [crates/yosoi/src/internal/engine/projection/outcome/reasons.rs](../../../crates/yosoi/src/internal/engine/projection/outcome/reasons.rs) | 7 | `family: yosoi_web_capture::WebArtifactFamily,` (line 37) |
| [crates/yosoi/src/internal/engine/request/execution/outcome/failure.rs](../../../crates/yosoi/src/internal/engine/request/execution/outcome/failure.rs) | 19 | `MissingExecutionContext,` (line 18) |
| [crates/yosoi/src/internal/engine/request/execution/outcome/response.rs](../../../crates/yosoi/src/internal/engine/request/execution/outcome/response.rs) | 2 | `Completed,` (line 73) |
| [crates/yosoi/src/internal/engine/search/outcome.rs](../../../crates/yosoi/src/internal/engine/search/outcome.rs) | 69 | `pub acquisition: Option<AcquisitionKind>,` (line 21) |
| [crates/yosoi/src/internal/engine/search/preparation.rs](../../../crates/yosoi/src/internal/engine/search/preparation.rs) | 3 | `NoProviderConfigured,` (line 18) |
| [crates/yosoi/src/internal/engine/search/query.rs](../../../crates/yosoi/src/internal/engine/search/query.rs) | 5 | `Empty,` (line 14) |
| [crates/yosoi/src/internal/engine/search/result/page.rs](../../../crates/yosoi/src/internal/engine/search/result/page.rs) | 4 | `pub fn hits(&self) -> &[SearchHit] {` (line 29) |
| [crates/yosoi/src/internal/engine/search/result/types.rs](../../../crates/yosoi/src/internal/engine/search/result/types.rs) | 55 | `pub fn parse(value: &str) -> Result<Self, WebUrlParseError> {` (line 12) |
| [crates/yosoi/src/internal/extractor/mod.rs](../../../crates/yosoi/src/internal/extractor/mod.rs) | 37 | `pub enum Extracted<T: Contract> {` (line 19) |
| [crates/yosoi/src/internal/map/mod.rs](../../../crates/yosoi/src/internal/map/mod.rs) | 135 | `pub enum DiscoverySource {` (line 15) |
| [crates/yosoi/src/internal/map/providers.rs](../../../crates/yosoi/src/internal/map/providers.rs) | 4 | `CrtSh,` (line 21) |
| [crates/yosoi/src/internal/policy/error.rs](../../../crates/yosoi/src/internal/policy/error.rs) | 2 | `SearchPlanExceedsTotalResults { required: u32, limit: u32 },` (line 94) |
| [crates/yosoi/src/internal/policy/policy/count.rs](../../../crates/yosoi/src/internal/policy/policy/count.rs) | 2 | `pub const fn get(self) -> u64 {` (line 10) |
| [crates/yosoi/src/internal/policy/policy/documents.rs](../../../crates/yosoi/src/internal/policy/policy/documents.rs) | 3 | `pub max_input_bytes: AddressableByteLimit,` (line 9) |
| [crates/yosoi/src/internal/policy/policy/flow.rs](../../../crates/yosoi/src/internal/policy/policy/flow.rs) | 1 | `pub const fn is_default(&self) -> bool {` (line 43) |
| [crates/yosoi/src/internal/policy/policy/locators.rs](../../../crates/yosoi/src/internal/policy/policy/locators.rs) | 7 | `pub max_selector_visits: CountLimit,` (line 9) |
| [crates/yosoi/src/internal/policy/policy/page.rs](../../../crates/yosoi/src/internal/policy/policy/page.rs) | 1 | `Browser { mode: BrowserMode },` (line 31) |
| [crates/yosoi/src/internal/policy/policy/redirect.rs](../../../crates/yosoi/src/internal/policy/policy/redirect.rs) | 2 | `max_hops: RedirectHopLimit,` (line 75) |
| [crates/yosoi/src/internal/policy/policy/search/provider.rs](../../../crates/yosoi/src/internal/policy/policy/search/provider.rs) | 8 | `Brave,` (line 17) |
| [crates/yosoi/src/internal/types/browser.rs](../../../crates/yosoi/src/internal/types/browser.rs) | 14 | `Headless,` (line 47) |
| [crates/yosoi/src/internal/web_capture/source.rs](../../../crates/yosoi/src/internal/web_capture/source.rs) | 3 | `pub enum UnknownReason {` (line 92) |
| [crates/yosoi/src/internal/web_capture/source/decode.rs](../../../crates/yosoi/src/internal/web_capture/source/decode.rs) | 9 | `pub enum DecodingErrorCode {` (line 38) |
| [crates/yosoi/src/request/authoring.rs](../../../crates/yosoi/src/request/authoring.rs) | 2 | `pub fn in_session<'session>(` (line 103) |
| [crates/yosoi/src/request/outcomes.rs](../../../crates/yosoi/src/request/outcomes.rs) | 9 | `Completed,` (line 15) |
| [crates/yosoi/src/session.rs](../../../crates/yosoi/src/session.rs) | 90 | `pub enum ActionKind {` (line 63) |
| [crates/yosoi/src/session/evaluation.rs](../../../crates/yosoi/src/session/evaluation.rs) | 6 | `pub async fn evaluate(&self, source: &str) -> Result<OperationReceipt, SessionError> {` (line 10) |
| [crates/yosoi/src/session/until.rs](../../../crates/yosoi/src/session/until.rs) | 26 | `pub session_id: String,` (line 20) |
| [crates/yosoi/src/view.rs](../../../crates/yosoi/src/view.rs) | 53 | `pub fn observation_id(&self) -> &str {` (line 39) |

## Python gaps by module

| Module | Missing docstrings | Field candidates |
| --- | ---: | ---: |
| [python/yosoi/browser.py](../../../python/yosoi/browser.py) | 64 | 139 |
| [python/yosoi/cancellation.py](../../../python/yosoi/cancellation.py) | 4 | 0 |
| [python/yosoi/contracts.py](../../../python/yosoi/contracts.py) | 32 | 51 |
| [python/yosoi/documents.py](../../../python/yosoi/documents.py) | 35 | 7 |
| [python/yosoi/identities.py](../../../python/yosoi/identities.py) | 14 | 0 |
| [python/yosoi/locators.py](../../../python/yosoi/locators.py) | 46 | 24 |
| [python/yosoi/map.py](../../../python/yosoi/map.py) | 40 | 69 |
| [python/yosoi/outcomes.py](../../../python/yosoi/outcomes.py) | 47 | 77 |
| [python/yosoi/policy.py](../../../python/yosoi/policy.py) | 56 | 125 |
| [python/yosoi/request.py](../../../python/yosoi/request.py) | 33 | 32 |
| [python/yosoi/runtime_contracts.py](../../../python/yosoi/runtime_contracts.py) | 58 | 34 |
| [python/yosoi/scalars.py](../../../python/yosoi/scalars.py) | 37 | 0 |
| [python/yosoi/search.py](../../../python/yosoi/search.py) | 61 | 77 |

## Initial behavior examples

- `ResponseTermination::Completed`: no observed caller cancellation; failures and partial outcomes remain possible, including a completed empty sequence.
- `ResponseTermination::Cancelled`: pre-cancelled tokens or cancellation observed during execution retain recorded outcomes and mark later acquisitions not started. External effects are not rolled back. A late signal after the final observation does not rewrite a completed response.
- Python `CancellationToken`: cooperative shared signal, immediate idempotent cancellation request, and asynchronous observation. Google-style Ruff D checks pass for this module.

## Completed source coverage and local evidence

- SDK and re-exported Contract derive crate deny `missing_docs`. The all-features SDK library check passes; a renamed-dependency consumer denying the lint also passes, covering generated candidate types, methods, and field descriptions. The consumer reports two existing default-feature dead-code warnings.
- Public Python package enables Ruff D with the Google convention. Package-wide Ruff passes; a separate audit finds zero missing descriptions among declared public model fields, excluding Pydantic class configuration. Non-package tests/examples/tooling retain their separate authoring scope.
- Python executable ASTs match current main after removing documentation expressions. Rust source review found documentation, generated documentation attributes, and formatting changes only. No runtime behavior was changed.
- Nine Rust model tests, two Python extraction tests, and 21 existing documentation tooling tests pass locally. The real compiler fixture tests variant, nested-field, and method comment retention.
- An unsigned local reference generated from consolidated source `e3df268213c60378ee923a838b24be05d0954233` with browser, CLI, scanner, GIF, and FFmpeg features contains 389 pages and passes integrity verification. Inspected output retains both ResponseTermination variants, 255 documented nested variant fields, and the re-exported Contract derive prose.
- Python extraction generates 486 pages. Work cleanup/cancellation methods, SessionPolicy fields, RuntimeContractOutcome strict acceptance, and alias pages retain source explanations. Port 4321 served the new Python method and field prose during local review. Its user-managed process runs from default CascadingLabsFE and selects neighboring default Yosoi.
- Final prepared frontend inputs contain 959 pages, including 389 Rust API pages. A later served-Rust request verified the refreshed source SHA and ResponseTermination variant prose. The server was left under user control.
- Shared public Markdown validation passes (570 pages, four assets, navigation). The full shared format gate reports existing review and concurrently authored concept-page formatting failures; these unrelated pages are excluded from this source-documentation PR. No hosted CI, merge, release, or deployed behavior is claimed.
