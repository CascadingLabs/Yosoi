#[path = "../../yosoi-web-capture-direct-http/tests/support/direct_http_fixture.rs"]
mod fixture;

use std::{env, error::Error, ffi::OsString, fs, io, path::Path, process::Command};

use fixture::{FixtureService, Protocol, Response as FixtureResponse};
use tempfile::tempdir;
use tokio::runtime::Builder;
use tokio::task::spawn_blocking;
use yosoi::prelude as ys;

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

const CHILD_ROLE: &str = "YOSOI_ARCHIVED_REQUEST_CHILD_ROLE";
const CHILD_ROOT: &str = "YOSOI_ARCHIVED_REQUEST_CHILD_ROOT";
const CHILD_REFERENCE: &str = "YOSOI_ARCHIVED_REQUEST_CHILD_REFERENCE";
const CHILD_TARGET: &str = "YOSOI_ARCHIVED_REQUEST_CHILD_TARGET";

#[tokio::test]
async fn request_archive_crosses_process_boundary_before_offline_location() -> TestResult {
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/golden".to_owned(),
            FixtureResponse::bytes(
                200,
                Some("text/html; charset=utf-8"),
                b"<!doctype html><main>Archive golden product</main>",
            ),
        )],
    )
    .await;
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let reference = temporary.path().join("evaluation-run-ref.txt");

    run_child(
        "subprocess_archived_request_writer",
        "write",
        &root,
        &reference,
        Some(service.url("/golden")),
    )
    .await?;
    let request_count = service.requests().await.len();
    service.shutdown().await;
    if request_count != 1 {
        return Err(io::Error::other("writer did not perform exactly one request").into());
    }

    run_child(
        "subprocess_archived_request_reader",
        "read",
        &root,
        &reference,
        None,
    )
    .await
}

#[tokio::test]
async fn ordinary_send_child_does_not_create_default_archive() -> TestResult {
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/ordinary".to_owned(),
            FixtureResponse::bytes(200, Some("text/plain; charset=utf-8"), b"ordinary"),
        )],
    )
    .await;
    let temporary = tempdir()?;
    let working_directory = temporary.path().to_owned();
    run_ordinary_child(&working_directory, service.url("/ordinary")).await?;
    let request_count = service.requests().await.len();
    service.shutdown().await;
    if request_count != 1 {
        return Err(io::Error::other("ordinary child did not perform exactly one request").into());
    }
    if working_directory.join(".yosoi").exists() {
        return Err(io::Error::other("ordinary send created a default .yosoi Archive").into());
    }
    Ok(())
}

async fn run_ordinary_child(working_directory: &Path, target: String) -> TestResult {
    let executable = env::current_exe()?;
    let working_directory = working_directory.to_owned();
    let status = spawn_blocking(move || {
        Command::new(executable)
            .args([
                "--ignored",
                "--exact",
                "subprocess_ordinary_send",
                "--nocapture",
            ])
            .current_dir(working_directory)
            .env(CHILD_ROLE, "ordinary")
            .env(CHILD_TARGET, target)
            .status()
    })
    .await??;
    if !status.success() {
        return Err(io::Error::other(format!("ordinary child failed with {status}")).into());
    }
    Ok(())
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
        return Err(io::Error::other(format!("Archive child failed with {status}")).into());
    }
    Ok(())
}

#[test]
#[ignore = "invoked by request_archive_crosses_process_boundary_before_offline_location"]
fn subprocess_archived_request_writer() -> TestResult {
    require_role("write")?;
    let root = required_os(CHILD_ROOT)?;
    let reference_path = required_os(CHILD_REFERENCE)?;
    let target = env::var(CHILD_TARGET)?;
    let runtime = Builder::new_current_thread().enable_all().build()?;
    runtime.block_on(async move {
        let archive = ys::Archive::open(root).await?;
        let archived = ys::request::new(target).send_archived(&archive).await?;
        let request_run: ys::RequestRunRecord = archive.read(archived.request_run_ref()).await?;
        let attempt = request_run
            .attempts()
            .first()
            .ok_or_else(|| io::Error::other("request run omitted its completed attempt"))?;
        let ys::RequestAttemptOutcome::Completed {
            capture, documents, ..
        } = attempt.outcome()
        else {
            return Err(io::Error::other("request attempt did not complete").into());
        };
        let inputs = documents
            .iter()
            .filter_map(|record| match record.outcome() {
                ys::RequestDocumentOutcome::Produced { document }
                | ys::RequestDocumentOutcome::Partial {
                    document: Some(document),
                    ..
                } => Some(document.clone()),
                ys::RequestDocumentOutcome::Partial { document: None, .. }
                | ys::RequestDocumentOutcome::Unavailable { .. }
                | ys::RequestDocumentOutcome::Unprojectable { .. } => None,
            })
            .collect::<Vec<_>>();
        let plan = ys::Plan::new([ys::output(
            "product",
            ys::tree_text_contains("Archive golden product")?.node(),
        )?])?;
        let plan_ref = archive.write(&plan).await?;
        let evaluation = ys::EvaluationRunRecord::try_new(
            capture.clone(),
            archived.policy_ref().clone(),
            plan_ref,
            None,
            inputs,
        )?;
        let evaluation_ref = archive.write(&evaluation).await?;
        fs::write(reference_path, evaluation_ref.to_string())?;
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    })
}

#[test]
#[ignore = "invoked by request_archive_crosses_process_boundary_before_offline_location"]
fn subprocess_archived_request_reader() -> TestResult {
    require_role("read")?;
    if env::var_os(CHILD_TARGET).is_some() {
        return Err(
            io::Error::other("offline reader unexpectedly received a request target").into(),
        );
    }
    let root = required_os(CHILD_ROOT)?;
    let reference_path = required_os(CHILD_REFERENCE)?;
    let reference: ys::EvaluationRunArchiveRef = fs::read_to_string(reference_path)?.parse()?;
    let runtime = Builder::new_current_thread().enable_all().build()?;
    runtime.block_on(async move {
        let archive = ys::Archive::open(root).await?;
        let evaluation: ys::EvaluationRunRecord = archive.read(&reference).await?;
        let _capture: ys::CaptureBundle = archive.read(evaluation.capture()).await?;
        let _policy: ys::Policy = archive.read(evaluation.policy()).await?;
        let plan: ys::Plan = archive.read(evaluation.plan()).await?;
        let input = evaluation
            .documents()
            .first()
            .ok_or_else(|| io::Error::other("evaluation run omitted its Document"))?;
        let document = ys::Document::from_archived(archive.read(input.document()).await?);
        if !matches!(document.locate(&plan), ys::LocateOutcome::Matched { .. }) {
            return Err(io::Error::other("offline locator did not match archived evidence").into());
        }
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    })
}

#[test]
#[ignore = "invoked by ordinary_send_child_does_not_create_default_archive"]
fn subprocess_ordinary_send() -> TestResult {
    require_role("ordinary")?;
    let target = env::var(CHILD_TARGET)?;
    let runtime = Builder::new_current_thread().enable_all().build()?;
    runtime.block_on(async move {
        let response = ys::request::new(target).send().await?;
        if response.attempts().len() != 1 {
            return Err(io::Error::other("ordinary send did not complete one attempt").into());
        }
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    })
}

fn require_role(expected: &str) -> TestResult {
    let observed = env::var(CHILD_ROLE)?;
    if observed != expected {
        return Err(io::Error::other(format!(
            "expected Archive child role {expected}, observed {observed}"
        ))
        .into());
    }
    Ok(())
}

fn required_os(name: &str) -> TestResult<OsString> {
    env::var_os(name)
        .ok_or_else(|| io::Error::other(format!("missing Archive child environment {name}")).into())
}
