#[path = "../../yosoi-web-capture-direct-http/tests/support/direct_http_fixture.rs"]
mod fixture;

use std::{env, error::Error, ffi::OsString, fs, io, path::Path, process::Command};

use fixture::{FixtureService, Protocol, Response as FixtureResponse};
use tempfile::tempdir;
use tokio::{runtime::Builder, task::spawn_blocking};
use yosoi_engine as ys;
use yosoi_engine::archived::{
    ContractFieldValue as ArchivedFieldValue, ContractOutcome as ArchivedOutcome,
    ContractValue as ArchivedValue, FieldIssueKind as ArchivedFieldIssueKind,
};
use yosoi_engine::{locator, request};

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

const CHILD_ROLE: &str = "YOSOI_EVALUATION_RESULT_CHILD_ROLE";
const CHILD_ROOT: &str = "YOSOI_EVALUATION_RESULT_CHILD_ROOT";
const CHILD_REFERENCE: &str = "YOSOI_EVALUATION_RESULT_CHILD_REFERENCE";
const CHILD_TARGET: &str = "YOSOI_EVALUATION_RESULT_CHILD_TARGET";

#[derive(ys::Contract)]
#[ys(id = "author_profile", description = "One archived author profile")]
struct AuthorProfile {
    #[ys(
        description = "Author display name",
        locator = locator::text_literal("John Doe").text()
    )]
    author: String,

    #[ys(
        description = "Author hourly rate",
        locator = locator::text_literal("$12.00").text()
    )]
    rate: ys::Money,

    #[ys(
        description = "Optional author role",
        locator = locator::text_literal("Staff").text()
    )]
    role: Option<String>,

    #[ys(
        description = "Author specialties",
        locator = locator::text_literal("Rust").text()
    )]
    specialties: Vec<String>,
}

#[derive(ys::Contract)]
#[ys(id = "other_author", description = "A different archived Contract")]
struct OtherAuthor {
    #[ys(
        description = "Another author name",
        locator = locator::text_literal("John Doe").text()
    )]
    name: String,
}

#[tokio::test]
async fn archives_locator_value_and_validated_contract() -> TestResult {
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/author".to_owned(),
            FixtureResponse::bytes(
                200,
                Some("text/plain; charset=utf-8"),
                b"John Doe\n$12.00\nStaff\nRust\nRust",
            ),
        )],
    )
    .await;
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = ys::Archive::open(&root).await?;
    let contract_ref = write_author_result(&archive, service.url("/author")).await?;
    let request_count = service.requests().await.len();
    service.shutdown().await;
    if request_count != 1 {
        return Err(io::Error::other("author fixture did not receive one request").into());
    }
    let reference_text = contract_ref.to_string();
    drop(archive);

    let archive = ys::Archive::open(&root).await?;
    assert_portable_author_result(&archive, &reference_text).await
}

#[tokio::test]
async fn archives_contract_validation_issues() -> TestResult {
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/author-missing-rate".to_owned(),
            FixtureResponse::bytes(
                200,
                Some("text/plain; charset=utf-8"),
                b"John Doe\nStaff\nRust",
            ),
        )],
    )
    .await;
    let temporary = tempdir()?;
    let archive = ys::Archive::open(temporary.path().join(".yosoi")).await?;
    let contract_ref = write_author_result(&archive, service.url("/author-missing-rate")).await?;
    let request_count = service.requests().await.len();
    service.shutdown().await;
    if request_count != 1 {
        return Err(
            io::Error::other("validation issue fixture did not receive one request").into(),
        );
    }
    let result: ys::ContractRunRecord = archive.read(&contract_ref).await?;
    let ArchivedOutcome::Evaluated {
        records, issues, ..
    } = result.outcome()
    else {
        return Err(io::Error::other("validation issue result was not Evaluated").into());
    };
    if !records.is_empty() || issues.len() != 1 {
        return Err(io::Error::other("missing rate did not produce one archived issue").into());
    }
    let rate = issues
        .first()
        .and_then(|issue| issue.fields().first())
        .ok_or_else(|| io::Error::other("archived issue omitted its rate field"))?;
    if rate.field().as_str() != "rate" || rate.kind() != &ArchivedFieldIssueKind::MissingRequired {
        return Err(io::Error::other("archived issue changed the missing-rate diagnosis").into());
    }
    let author_evidence = issues
        .first()
        .and_then(|issue| {
            issue
                .candidate_fields()
                .iter()
                .find(|field| field.id().as_str() == "author")
        })
        .ok_or_else(|| io::Error::other("archived issue omitted candidate author evidence"))?;
    if author_evidence.evidence().len() != 1 {
        return Err(io::Error::other("archived issue changed candidate author evidence").into());
    }
    let values: Vec<AuthorProfile> = result.values()?;
    if !values.is_empty() {
        return Err(io::Error::other("issues-only result restored a validated value").into());
    }
    if !matches!(
        result.values::<OtherAuthor>(),
        Err(ys::ContractRunRecordError::CompiledContractSchemaMismatch)
    ) {
        return Err(io::Error::other("issues-only result accepted another Contract schema").into());
    }
    Ok(())
}

#[test]
fn non_evaluated_values_still_validate_the_compiled_contract() -> TestResult {
    let locator_ref: ys::LocatorRunArchiveRef =
        "locator-run:v1:123e4567-e89b-42d3-a456-426614174000".parse()?;
    let schema_ref: ys::ContractSchemaArchiveRef =
        "contract-schema:v1:123e4567-e89b-42d3-a456-426614174001".parse()?;
    let document = ys::Document::text("missing-author", b"Nobody".to_vec())?;
    let outcome = ys::ContractOutcome::<AuthorProfile>::NoMatch {
        document_id: document.id().clone(),
    };
    let run = ys::ContractRunRecord::new(locator_ref, schema_ref, &outcome)?;
    let values: Vec<AuthorProfile> = run.values()?;
    if !values.is_empty() {
        return Err(io::Error::other("NoMatch restored a validated value").into());
    }
    if !matches!(
        run.values::<OtherAuthor>(),
        Err(ys::ContractRunRecordError::CompiledContractSchemaMismatch)
    ) {
        return Err(io::Error::other("NoMatch accepted another Contract schema").into());
    }
    Ok(())
}

#[tokio::test]
async fn contract_result_crosses_process_boundary_without_a_target() -> TestResult {
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/author-process".to_owned(),
            FixtureResponse::bytes(
                200,
                Some("text/plain; charset=utf-8"),
                b"John Doe\n$12.00\nStaff\nRust\nRust",
            ),
        )],
    )
    .await;
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let reference = temporary.path().join("contract-run-ref.txt");
    run_child(
        "subprocess_evaluation_result_writer",
        "write",
        &root,
        &reference,
        Some(service.url("/author-process")),
    )
    .await?;
    let request_count = service.requests().await.len();
    service.shutdown().await;
    if request_count != 1 {
        return Err(io::Error::other("result writer did not perform exactly one request").into());
    }
    run_child(
        "subprocess_evaluation_result_reader",
        "read",
        &root,
        &reference,
        None,
    )
    .await?;
    run_child(
        "subprocess_evaluation_replay_reader",
        "replay",
        &root,
        &reference,
        None,
    )
    .await
}

async fn run_child(
    test_name: &str,
    role: &str,
    root: &Path,
    reference: &Path,
    target: Option<String>,
) -> TestResult {
    let executable = env::current_exe()?;
    let test_name = test_name.to_owned();
    let role = role.to_owned();
    let root = root.to_owned();
    let reference = reference.to_owned();
    let status = spawn_blocking(move || {
        let mut command = Command::new(executable);
        command
            .args(["--ignored", "--exact", &test_name, "--nocapture"])
            .env(CHILD_ROLE, role)
            .env(CHILD_ROOT, root)
            .env(CHILD_REFERENCE, reference);
        if let Some(target) = target {
            command.env(CHILD_TARGET, target);
        }
        command.status()
    })
    .await??;
    if !status.success() {
        return Err(
            io::Error::other(format!("evaluation result child failed with {status}")).into(),
        );
    }
    Ok(())
}

#[test]
#[ignore = "invoked by contract_result_crosses_process_boundary_without_a_target"]
fn subprocess_evaluation_result_writer() -> TestResult {
    require_role("write")?;
    let root = required_os(CHILD_ROOT)?;
    let reference = required_os(CHILD_REFERENCE)?;
    let target = env::var(CHILD_TARGET)?;
    let runtime = Builder::new_current_thread().enable_all().build()?;
    runtime.block_on(async move {
        let archive = ys::Archive::open(root).await?;
        let contract_ref = write_author_result(&archive, target).await?;
        fs::write(reference, contract_ref.to_string())?;
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    })
}

#[test]
#[ignore = "invoked by contract_result_crosses_process_boundary_without_a_target"]
fn subprocess_evaluation_result_reader() -> TestResult {
    require_role("read")?;
    if env::var_os(CHILD_TARGET).is_some() {
        return Err(
            io::Error::other("archived result reader unexpectedly received a target").into(),
        );
    }
    let root = required_os(CHILD_ROOT)?;
    let reference = fs::read_to_string(required_os(CHILD_REFERENCE)?)?;
    let runtime = Builder::new_current_thread().enable_all().build()?;
    runtime.block_on(async move {
        let archive = ys::Archive::open(root).await?;
        assert_portable_author_result(&archive, &reference).await
    })
}

#[test]
#[ignore = "invoked by contract_result_crosses_process_boundary_without_a_target"]
fn subprocess_evaluation_replay_reader() -> TestResult {
    require_role("replay")?;
    if env::var_os(CHILD_TARGET).is_some() {
        return Err(
            io::Error::other("offline replay reader unexpectedly received a target").into(),
        );
    }
    let root = required_os(CHILD_ROOT)?;
    let reference: ys::ContractRunArchiveRef =
        fs::read_to_string(required_os(CHILD_REFERENCE)?)?.parse()?;
    let runtime = Builder::new_current_thread().enable_all().build()?;
    runtime.block_on(async move {
        let archive = ys::Archive::open(root).await?;
        let contract: ys::ContractRunRecord = archive.read(&reference).await?;
        assert_typed_author_values(&contract)?;
        let locator: ys::LocatorRunRecord = archive.read(contract.locator_run()).await?;
        let evaluation: ys::EvaluationRunRecord = archive.read(locator.evaluation()).await?;
        let input = evaluation
            .documents()
            .iter()
            .find(|input| input.document() == locator.document())
            .ok_or_else(|| io::Error::other("offline replay lost its Document input"))?;
        let document = ys::Document::from_archived(archive.read(input.document()).await?);
        let plan: ys::Plan = archive.read(evaluation.plan()).await?;
        let located = document.locate(&plan);
        if &located != locator.outcome() {
            return Err(
                io::Error::other("offline LocateOutcome differs from archived result").into(),
            );
        }
        let replayed_outcome = AuthorProfile::extract(&located).validate();
        let replayed = ys::ContractRunRecord::new(
            contract.locator_run().clone(),
            contract.contract_schema().clone(),
            &replayed_outcome,
        )?;
        if replayed.outcome() != contract.outcome() {
            return Err(
                io::Error::other("offline Contract outcome differs from archived result").into(),
            );
        }
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    })
}

fn require_role(expected: &str) -> TestResult {
    let observed = env::var(CHILD_ROLE)?;
    if observed != expected {
        return Err(io::Error::other(format!(
            "expected evaluation result child role {expected}, observed {observed}"
        ))
        .into());
    }
    Ok(())
}

fn required_os(name: &str) -> TestResult<OsString> {
    env::var_os(name).ok_or_else(|| {
        io::Error::other(format!(
            "missing evaluation result child environment {name}"
        ))
        .into()
    })
}

async fn write_author_result(
    archive: &ys::Archive,
    target: String,
) -> TestResult<ys::ContractRunArchiveRef> {
    let archived = request::new(target).send_archived(archive).await?;
    let request_run: ys::RequestRunRecord = archive.read(archived.request_run_ref()).await?;
    let (capture_ref, input) = produced_document(&request_run)?;
    let document = ys::Document::from_archived(archive.read(input.document()).await?);
    let plan_ref = archive.write(AuthorProfile::plan()?).await?;
    let schema_ref = archive.write(AuthorProfile::schema()?).await?;
    let evaluation = ys::EvaluationRunRecord::try_new(
        capture_ref,
        archived.policy_ref().clone(),
        plan_ref,
        Some(schema_ref.clone()),
        vec![input.clone()],
    )?;
    let evaluation_ref = archive.write(&evaluation).await?;

    let located = AuthorProfile::locate(&document)?;
    let locator_run =
        ys::LocatorRunRecord::new(evaluation_ref, input.document().clone(), located.clone());
    let locator_ref = archive.write(&locator_run).await?;
    let contract_outcome = AuthorProfile::extract(&located).validate();
    let other_schema_ref = archive.write(OtherAuthor::schema()?).await?;
    let wrong_schema =
        ys::ContractRunRecord::new(locator_ref.clone(), other_schema_ref, &contract_outcome)?;
    if !matches!(
        archive.write(&wrong_schema).await,
        Err(ys::ArchiveError::InvalidContractRun(
            ys::ContractRunRecordError::ContractSchemaNotInEvaluation
        ))
    ) {
        return Err(io::Error::other("ContractRun accepted the wrong schema reference").into());
    }
    let contract_run = ys::ContractRunRecord::new(locator_ref, schema_ref, &contract_outcome)?;
    assert_typed_author_values(&contract_run)?;
    if format!("{contract_run:?}").contains("John Doe") {
        return Err(io::Error::other("ContractRun Debug exposed archived values").into());
    }
    Ok(archive.write(&contract_run).await?)
}

fn assert_typed_author_values(run: &ys::ContractRunRecord) -> TestResult {
    let authors: Vec<AuthorProfile> = run.values()?;
    let Some(author) = authors.first() else {
        return Ok(());
    };
    if author.author != "John Doe"
        || author.rate.minor_units() != 1_200
        || author.role.as_deref() != Some("Staff")
        || author.specialties != ["Rust".to_owned(), "Rust".to_owned()]
    {
        return Err(io::Error::other("archived Contract changed typed values").into());
    }
    if !matches!(
        run.values::<OtherAuthor>(),
        Err(ys::ContractRunRecordError::CompiledContractSchemaMismatch)
    ) {
        return Err(io::Error::other("archived values accepted another Contract schema").into());
    }
    Ok(())
}

fn produced_document(
    request_run: &ys::RequestRunRecord,
) -> TestResult<(ys::CaptureArchiveRef, ys::ArchivedDocumentInput)> {
    let attempt = request_run
        .attempts()
        .first()
        .ok_or_else(|| io::Error::other("RequestRun omitted its completed attempt"))?;
    let ys::RequestAttemptOutcome::Completed {
        capture, documents, ..
    } = attempt.outcome()
    else {
        return Err(io::Error::other("request attempt did not complete").into());
    };
    let record = documents
        .first()
        .ok_or_else(|| io::Error::other("request attempt omitted its Document outcome"))?;
    let ys::RequestDocumentOutcome::Produced { document } = record.outcome() else {
        return Err(io::Error::other("request did not produce its response Document").into());
    };
    Ok((capture.clone(), document.clone()))
}

async fn assert_portable_author_result(archive: &ys::Archive, reference: &str) -> TestResult {
    let reference: ys::ContractRunArchiveRef = reference.parse()?;
    let result: ys::ContractRunRecord = archive.read(&reference).await?;
    let ArchivedOutcome::Evaluated {
        records,
        issues,
        extraction_diagnostics,
        ..
    } = result.outcome()
    else {
        return Err(io::Error::other("archived Contract result was not Evaluated").into());
    };
    if !issues.is_empty() || !extraction_diagnostics.is_empty() || records.len() != 1 {
        return Err(io::Error::other("archived Contract result retained unexpected issues").into());
    }
    let record = records
        .first()
        .ok_or_else(|| io::Error::other("archived Contract result omitted its record"))?;
    let fields = record.fields();
    let author = fields
        .iter()
        .find(|field| field.id().as_str() == "author")
        .ok_or_else(|| io::Error::other("archived Contract result omitted author"))?;
    if author.value()
        != &(ArchivedFieldValue::ExactlyOne {
            value: ArchivedValue::String {
                value: "John Doe".to_owned(),
            },
        })
    {
        return Err(io::Error::other("archived author value was not John Doe").into());
    }
    let rate = fields
        .iter()
        .find(|field| field.id().as_str() == "rate")
        .ok_or_else(|| io::Error::other("archived Contract result omitted rate"))?;
    if rate.value()
        != &(ArchivedFieldValue::ExactlyOne {
            value: ArchivedValue::MoneyUsd { minor_units: 1_200 },
        })
    {
        return Err(io::Error::other("archived rate did not retain $12.00").into());
    }
    let role = fields
        .iter()
        .find(|field| field.id().as_str() == "role")
        .ok_or_else(|| io::Error::other("archived Contract result omitted role"))?;
    if role.value()
        != &(ArchivedFieldValue::ZeroOrOne {
            value: Some(ArchivedValue::String {
                value: "Staff".to_owned(),
            }),
        })
    {
        return Err(io::Error::other("archived optional role changed").into());
    }
    let specialties = fields
        .iter()
        .find(|field| field.id().as_str() == "specialties")
        .ok_or_else(|| io::Error::other("archived Contract result omitted specialties"))?;
    if specialties.value()
        != &(ArchivedFieldValue::Many {
            values: vec![
                ArchivedValue::String {
                    value: "Rust".to_owned(),
                },
                ArchivedValue::String {
                    value: "Rust".to_owned(),
                },
            ],
        })
    {
        return Err(io::Error::other("archived repeated specialties changed").into());
    }
    let specialty_evidence = record
        .evidence()
        .iter()
        .find(|field| field.id().as_str() == "specialties")
        .ok_or_else(|| io::Error::other("portable record omitted specialty evidence"))?;
    if specialty_evidence.evidence().len() != 2 {
        return Err(io::Error::other("archived repeated evidence changed").into());
    }
    Ok(())
}
