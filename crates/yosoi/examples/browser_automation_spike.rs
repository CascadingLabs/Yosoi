//! Controlled local-fixture proof for the first Session, Flow, Archive and View pass.
//!
//! Run with:
//! `cargo run -p yosoi --features browser --example browser_automation_spike -- <output-dir>`
//! Replay only archived evidence, without starting the local server or a browser:
//! `cargo run -p yosoi --features browser --example browser_automation_spike -- --replay <output-dir>`

use std::{
    env,
    error::Error,
    fs, io,
    net::Ipv4Addr,
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};

use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::oneshot,
    task::{JoinHandle, JoinSet},
};
use yosoi::{
    Archive, action,
    automation_record::{
        AutomationContext, AutomationRecord, AutomationRecordRef, OperationReceipt, OperationStatus,
    },
    documents::DocumentRef,
    flow::{self, Condition, FailureCapturePolicy, Flow, FlowOutcome, FlowTermination, Step},
    locators::{LocateOutcome, Plan, css, output},
    policy::{Acquisition, BrowserMode, DocumentRequest, Page, Policy},
    request::{self, AttemptState},
    session::{self, SessionError, SessionPolicy},
    view::{View, ViewError},
};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut arguments = env::args_os().skip(1);
    let first = arguments.next().ok_or_else(|| {
        io::Error::other("usage: browser_automation_spike <output-dir> | --replay <output-dir>")
    })?;
    if first.to_string_lossy() == "--replay" {
        let output_dir = arguments.next().map(PathBuf::from).ok_or_else(|| {
            io::Error::other("usage: browser_automation_spike --replay <output-dir>")
        })?;
        if arguments.next().is_some() {
            return Err(
                io::Error::other("unexpected argument after replay output directory").into(),
            );
        }
        return replay_spike(&output_dir).await;
    }
    let output_dir = PathBuf::from(first);
    if arguments.next().is_some() {
        return Err(io::Error::other("unexpected argument after output directory").into());
    }
    let fixture = LocalFixture::start().await?;
    let run = run_spike(&fixture.url, &output_dir).await;
    let shutdown = fixture.shutdown().await;
    run?;
    shutdown?;
    Ok(())
}

pub(crate) async fn run_spike(url: &str, output_dir: &Path) -> Result<(), Box<dyn Error>> {
    fs::create_dir_all(output_dir)?;
    let archive_root = output_dir.join("archive");
    let browser_policy = browser_policy()?;
    let effective_policy_identity = effective_policy_identity(&browser_policy)?;
    let flow_session_policy = SessionPolicy::default();

    // Ordinary Requests still follow the caller's explicit browser acquisition policy.
    let browser_response = request::new(url.to_owned())
        .bind(&browser_policy)
        .send()
        .await?;
    if !has_completed_browser_document(&browser_response) {
        return Err(io::Error::other(
            "simple Browser Request did not produce a rendered-DOM Document",
        )
        .into());
    }
    println!("simple Browser Request: Browser attempt and rendered-DOM Document completed");

    // Subscribe both watchers before navigation and two Work-bound Requests.
    let session = session::new()
        .bind(&browser_policy)
        .configure(SessionPolicy::default())
        .acquire()
        .await?;
    let mut watcher_one = session.watch();
    let mut watcher_two = session.watch();
    let work = session.work().await?;
    let navigation = work.navigate(url).await?;
    let first_navigation_event = watcher_one.next().await?;
    let second_navigation_event = watcher_two.next().await?;
    require_same_event(&navigation, &first_navigation_event)?;
    require_same_event(&navigation, &second_navigation_event)?;

    let first_work_response = request::new(url.to_owned()).with_work(&work).send().await?;
    if first_work_response.termination() != yosoi::ResponseTermination::Completed {
        return Err(io::Error::other("first Work-bound Request did not complete").into());
    }
    if !has_completed_browser_document(&first_work_response) {
        return Err(io::Error::other(
            "first Work-bound Request did not produce a rendered-DOM Document",
        )
        .into());
    }
    let first_request_event = watcher_one.next().await?;
    let first_request_event_copy = watcher_two.next().await?;
    require_same_event(&first_request_event, &first_request_event_copy)?;
    require_request_event_for_response(&first_request_event, &first_work_response)?;

    let drift_request_url = format!("{url}?variant=drift");
    let second_work_response = request::new(drift_request_url)
        .with_work(&work)
        .send()
        .await?;
    if second_work_response.termination() != yosoi::ResponseTermination::Completed {
        return Err(io::Error::other("second Work-bound Request did not complete").into());
    }
    if !has_completed_browser_document(&second_work_response) {
        return Err(io::Error::other(
            "second Work-bound Request did not produce a rendered-DOM Document",
        )
        .into());
    }
    let second_request_event = watcher_one.next().await?;
    let second_request_event_copy = watcher_two.next().await?;
    require_same_event(&second_request_event, &second_request_event_copy)?;
    require_request_event_for_response(&second_request_event, &second_work_response)?;
    if first_request_event.id == second_request_event.id
        || first_work_response.request_id() == second_work_response.request_id()
    {
        return Err(io::Error::other("two Work-bound Requests reused an identity").into());
    }

    let session_operations = vec![
        (*first_navigation_event).clone(),
        (*first_request_event).clone(),
        (*second_request_event).clone(),
    ];
    match work.evaluate("40 + 2").await {
        Err(SessionError::Denied) => {
            println!("default Session policy denied JavaScript before dispatch")
        }
        Err(error) => {
            return Err(
                io::Error::other(format!("unexpected default JavaScript result: {error}")).into(),
            );
        }
        Ok(_) => return Err(io::Error::other("default Session policy allowed JavaScript").into()),
    }
    watcher_one.close();
    watcher_two.close();
    work.release().await?;
    session.close().await?;
    let first_document = rendered_dom_document(&first_work_response)
        .ok_or_else(|| io::Error::other("first Work response lost its rendered-DOM Document"))?;
    let second_document = rendered_dom_document(&second_work_response)
        .ok_or_else(|| io::Error::other("second Work response lost its rendered-DOM Document"))?;
    let first_document_rows = count_document_matches(first_document, ".row")?;
    let second_document_rows = count_document_matches(second_document, ".row")?;
    if first_document_rows != 12 || second_document_rows != 4 {
        return Err(io::Error::other(format!(
            "retained Work response Documents had {first_document_rows} and {second_document_rows} rows after Session close"
        ))
        .into());
    }
    println!(
        "two same-Work Requests reached both watchers; after Session close, retained Documents located {first_document_rows} and {second_document_rows} rows"
    );

    // Build a live View while caller-owned Work remains open, before Archive persistence.
    let passing_flow = passing_flow();
    let flow_session = session::new()
        .bind(&browser_policy)
        .configure(flow_session_policy.clone())
        .acquire()
        .await?;
    let flow_work = flow_session.work().await?;
    let passing_outcome = navigating_flow(url, &passing_flow)
        .bind(&browser_policy)
        .with_lease(&flow_work)
        .invoke()
        .await?;
    require_terminal(&passing_outcome, FlowTermination::Completed)?;
    if !has_screenshot(&passing_outcome) {
        return Err(io::Error::other("passing Flow did not retain its screenshot").into());
    }
    let live_observation = flow_observation(&passing_outcome)?;
    let live_page = View::from_observation(live_observation, 3)?;
    let live_condition = Condition::CountAtLeast {
        selector: ".row".to_owned(),
        count: 12,
    };
    if !live_page.verify_condition(live_observation, &live_condition)? {
        return Err(io::Error::other("live View did not verify the baseline row count").into());
    }
    let live_cursor = live_page
        .next_cursor()
        .cloned()
        .ok_or_else(|| io::Error::other("live fixture DOM did not produce a second View page"))?;
    let live_second_page = View::continue_from(live_observation, &live_cursor)?;
    if live_page.rows().len() != 3 || live_second_page.rows().len() != 3 {
        return Err(io::Error::other("live View did not page three rows at a time").into());
    }
    println!("live View paged the open Work capture before Archive write and Session close");
    flow_work.release().await?;
    flow_session.close().await?;
    println!("explicit Work Flow: passing assertions and screenshot retained");

    // Default continuation preserves the assertion failure and then runs the screenshot.
    let failing_flow = flow::new([
        action::click("#advance"),
        action::assert(Condition::Exists {
            selector: "#missing".to_owned(),
        })
        .into(),
        action::screenshot(),
    ]);
    let failing_outcome = navigating_flow(url, &failing_flow).invoke().await?;
    require_terminal(&failing_outcome, FlowTermination::CompletedWithIssues)?;
    if failing_outcome.steps.len() != 4
        || failing_outcome
            .steps
            .get(2)
            .is_none_or(|step| step.receipt.status != OperationStatus::Rejected)
        || failing_outcome
            .steps
            .last()
            .is_none_or(|step| step.receipt.status != OperationStatus::Observed)
    {
        return Err(io::Error::other(
            "continued Flow did not retain its failure and later screenshot",
        )
        .into());
    }
    println!("managed Flow: failed assertion retained; later screenshot step ran");

    // JavaScript stays opt-in and runs on the same caller-held Work substrate.
    let js_policy = SessionPolicy {
        allow_arbitrary_js: true,
        ..SessionPolicy::default()
    };
    let js_session = session::new()
        .bind(&browser_policy)
        .configure(js_policy.clone())
        .acquire()
        .await?;
    let js_work = js_session.work().await?;
    js_work.navigate(url).await?;
    let value = js_work.evaluate("40 + 2").await?;
    if value.result.as_ref() != Some(&serde_json::json!(42)) {
        return Err(io::Error::other("opt-in JavaScript value result did not match 42").into());
    }
    let mutation = js_work
        .evaluate(
            "document.body.dataset.spikeMutation = 'recorded'; document.body.dataset.spikeMutation",
        )
        .await?;
    if mutation.result.as_ref() != Some(&serde_json::json!("recorded")) {
        return Err(io::Error::other("opt-in JavaScript mutation result was not retained").into());
    }
    let script_error = js_work
        .evaluate("(() => { throw new Error('intentional local fixture error'); })()")
        .await?;
    if script_error.status != OperationStatus::Unknown || script_error.error.is_none() {
        return Err(io::Error::other(
            "JavaScript exception was not retained as an unknown receipt",
        )
        .into());
    }
    let js_operations = vec![value, mutation, script_error];
    js_work.release().await?;
    js_session.close().await?;
    println!("opt-in JavaScript: value, mutation, and unknown exception receipts retained");

    // Persist the default-policy Session evidence and opt-in JavaScript evidence separately.
    let record = AutomationRecord::new(
        format!("browser-automation-{}", session::new_operation_id()),
        Vec::new(),
        session_operations,
    )?
    .with_context(automation_context(
        &effective_policy_identity,
        flow_session_policy.clone(),
        None,
    ))?
    .with_flow_outcome(passing_outcome.clone())?;
    let archive = Archive::open(&archive_root).await?;
    let record_ref = record.write_to(&archive).await?;
    let js_record = AutomationRecord::new(
        format!("browser-automation-js-{}", session::new_operation_id()),
        Vec::new(),
        js_operations,
    )?
    .with_context(automation_context(
        &effective_policy_identity,
        js_policy,
        Some(record_ref.clone()),
    ))?;
    let js_ref = js_record.write_to(&archive).await?;
    drop(archive);
    fs::write(
        output_dir.join("record_ref.json"),
        serde_json::to_vec_pretty(&record_ref)?,
    )?;
    fs::write(
        output_dir.join("js_ref.json"),
        serde_json::to_vec_pretty(&js_ref)?,
    )?;

    // Reopen the archive, verify the captured assertion offline, and page over captured DOM.
    let reopened_archive = Archive::open(&archive_root).await?;
    let reopened = AutomationRecord::read_from(&reopened_archive, &record_ref).await?;
    drop(reopened_archive);
    let archived_flow = reopened
        .flow_outcome()
        .ok_or_else(|| io::Error::other("reopened record has no Flow outcome"))?;
    let observation = archived_flow
        .steps
        .iter()
        .rev()
        .find_map(|step| step.receipt.observation.as_ref())
        .filter(|observation| observation.html.is_some())
        .ok_or_else(|| io::Error::other("reopened Flow has no HTML observation"))?;
    let first_page = View::from_observation(observation, 3)?;
    let condition = Condition::CountAtLeast {
        selector: ".row".to_owned(),
        count: 12,
    };
    if !first_page.verify_condition(observation, &condition)? {
        return Err(io::Error::other("offline archived assertion did not pass").into());
    }
    let cursor = first_page
        .next_cursor()
        .ok_or_else(|| io::Error::other("fixture DOM did not produce a second View page"))?;
    let second_page = View::continue_from(observation, cursor)?;
    println!(
        "archive reopened and verified offline; View page rows: {} then {}",
        first_page.rows().len(),
        second_page.rows().len()
    );
    println!("evidence directory: {}", output_dir.display());
    println!(
        "archive record reference: {}",
        serde_json::to_string(&record_ref)?
    );
    println!(
        "opt-in JavaScript child record reference: {}",
        serde_json::to_string(&js_ref)?
    );

    // Preserve a positive rerun linked to its parent record.
    let rerun = navigating_flow(url, &passing_flow)
        .bind(&browser_policy)
        .invoke()
        .await?;
    require_terminal(&rerun, FlowTermination::Completed)?;
    let rerun_record = AutomationRecord::new(
        format!("browser-automation-rerun-{}", session::new_operation_id()),
        Vec::new(),
        Vec::new(),
    )?
    .with_context(automation_context(
        &effective_policy_identity,
        flow_session_policy.clone(),
        Some(record_ref.clone()),
    ))?
    .with_flow_outcome(rerun)?;
    let drift_url = format!("{url}?variant=drift");
    let drift_outcome = navigating_flow(&drift_url, &passing_flow)
        .bind(&browser_policy)
        .invoke()
        .await?;
    require_terminal(&drift_outcome, FlowTermination::CompletedWithIssues)?;
    let drift_observation = validate_drift_artifact(&drift_outcome, &passing_flow, &drift_url)?;
    let drift_page = View::from_observation(drift_observation, 3)?;
    if !drift_page.verify_condition(
        drift_observation,
        &Condition::CountAtLeast {
            selector: ".row".to_owned(),
            count: 4,
        },
    )? || drift_page.verify_condition(
        drift_observation,
        &Condition::CountAtLeast {
            selector: ".row".to_owned(),
            count: 5,
        },
    )? {
        return Err(io::Error::other("drift View did not retain exactly four result rows").into());
    }
    match View::continue_from(drift_observation, &live_cursor) {
        Err(ViewError::ForeignCursor) => {}
        Err(error) => {
            return Err(io::Error::other(format!(
                "old live View cursor failed with the wrong typed error: {error}"
            ))
            .into());
        }
        Ok(_) => {
            return Err(io::Error::other(
                "old live View cursor was accepted against the changed capture",
            )
            .into());
        }
    }
    let archive = Archive::open(&archive_root).await?;
    let rerun_ref = rerun_record.write_to(&archive).await?;
    let drift_record = AutomationRecord::new(
        format!("browser-automation-drift-{}", session::new_operation_id()),
        Vec::new(),
        Vec::new(),
    )?
    .with_context(automation_context(
        &effective_policy_identity,
        flow_session_policy.clone(),
        Some(rerun_ref.clone()),
    ))?
    .with_flow_outcome(drift_outcome)?;
    let drift_ref = drift_record.write_to(&archive).await?;
    drop(archive);
    fs::write(
        output_dir.join("rerun_ref.json"),
        serde_json::to_vec_pretty(&rerun_ref)?,
    )?;
    fs::write(
        output_dir.join("drift_ref.json"),
        serde_json::to_vec_pretty(&drift_ref)?,
    )?;
    println!("live rerun after offline verification: completed");
    println!(
        "child record reference: {}",
        serde_json::to_string(&rerun_ref)?
    );
    println!("controlled drift rerun: typed failed assertion; old View cursor rejected");
    println!(
        "drift child record reference: {}",
        serde_json::to_string(&drift_ref)?
    );
    Ok(())
}

/// Reopens the supplied immutable record and evaluates only retained evidence.
pub(crate) async fn replay_spike(output_dir: &Path) -> Result<(), Box<dyn Error>> {
    let record_ref = read_record_ref(output_dir.join("record_ref.json"))?;
    let js_ref = read_record_ref(output_dir.join("js_ref.json"))?;
    let rerun_ref = read_record_ref(output_dir.join("rerun_ref.json"))?;
    let drift_ref = read_record_ref(output_dir.join("drift_ref.json"))?;
    let archive = Archive::open(output_dir.join("archive")).await?;
    let record = AutomationRecord::read_from(&archive, &record_ref).await?;
    let js_record = AutomationRecord::read_from(&archive, &js_ref).await?;
    let rerun_record = AutomationRecord::read_from(&archive, &rerun_ref).await?;
    let drift_record = AutomationRecord::read_from(&archive, &drift_ref).await?;
    drop(archive);
    let browser_policy = browser_policy()?;
    let policy_identity = effective_policy_identity(&browser_policy)?;
    let session_policy = SessionPolicy::default();
    let js_session_policy = SessionPolicy {
        allow_arbitrary_js: true,
        ..SessionPolicy::default()
    };
    validate_context(&record, &policy_identity, &session_policy, None)?;
    validate_context(
        &js_record,
        &policy_identity,
        &js_session_policy,
        Some(&record_ref),
    )?;
    validate_context(
        &rerun_record,
        &policy_identity,
        &session_policy,
        Some(&record_ref),
    )?;
    validate_context(
        &drift_record,
        &policy_identity,
        &session_policy,
        Some(&rerun_ref),
    )?;
    let original_context = record
        .context()
        .ok_or_else(|| io::Error::other("reopened record has no AutomationContext"))?;
    let js_context = js_record
        .context()
        .ok_or_else(|| io::Error::other("reopened JavaScript record has no AutomationContext"))?;
    let rerun_context = rerun_record
        .context()
        .ok_or_else(|| io::Error::other("reopened rerun has no AutomationContext"))?;
    let drift_context = drift_record
        .context()
        .ok_or_else(|| io::Error::other("reopened drift record has no AutomationContext"))?;
    if original_context.browser_identity != rerun_context.browser_identity
        || original_context.browser_identity != js_context.browser_identity
        || rerun_context.browser_identity != drift_context.browser_identity
        || original_context.source_revision != rerun_context.source_revision
        || original_context.source_revision != js_context.source_revision
        || rerun_context.source_revision != drift_context.source_revision
    {
        return Err(io::Error::other(
            "browser identity or source revision changed across the archived Flow chain",
        )
        .into());
    }
    validate_js_record(&js_record)?;
    println!("offline replay verified JavaScript receipts with allow_arbitrary_js=true");
    let expected_flow = passing_flow();
    let outcome = record
        .flow_outcome()
        .ok_or_else(|| io::Error::other("reopened record has no Flow outcome"))?;
    let rerun_outcome = rerun_record
        .flow_outcome()
        .ok_or_else(|| io::Error::other("reopened rerun has no Flow outcome"))?;
    let drift_outcome = drift_record
        .flow_outcome()
        .ok_or_else(|| io::Error::other("reopened drift record has no Flow outcome"))?;
    let source_url = flow_navigation_url(&outcome.flow)?;
    let drift_url = format!("{source_url}?variant=drift");
    let observation = validate_flow_artifact(outcome, &expected_flow, source_url)?;
    let rerun_observation = validate_flow_artifact(rerun_outcome, &expected_flow, source_url)?;
    let drift_observation = validate_drift_artifact(drift_outcome, &expected_flow, &drift_url)?;
    if outcome.flow != rerun_outcome.flow {
        return Err(
            io::Error::other("rerun Flow definition changed across Archive records").into(),
        );
    }
    let first_page = View::from_observation(observation, 3)?;
    let rerun_page = View::from_observation(rerun_observation, 3)?;
    for condition in [
        Condition::Exists {
            selector: "#status.ready".to_owned(),
        },
        Condition::CountAtLeast {
            selector: ".row".to_owned(),
            count: 12,
        },
    ] {
        if !first_page.verify_condition(observation, &condition)?
            || !rerun_page.verify_condition(rerun_observation, &condition)?
        {
            return Err(io::Error::other(format!(
                "offline archived condition did not pass: {condition:?}"
            ))
            .into());
        }
    }
    let cursor = first_page
        .next_cursor()
        .ok_or_else(|| io::Error::other("fixture DOM did not produce a second View page"))?;
    let second_page = View::continue_from(observation, cursor)?;
    let drift_page = View::from_observation(drift_observation, 3)?;
    if !drift_page.verify_condition(
        drift_observation,
        &Condition::CountAtLeast {
            selector: ".row".to_owned(),
            count: 4,
        },
    )? || drift_page.verify_condition(
        drift_observation,
        &Condition::CountAtLeast {
            selector: ".row".to_owned(),
            count: 5,
        },
    )? {
        return Err(
            io::Error::other("offline drift View did not retain exactly four result rows").into(),
        );
    }
    match View::continue_from(drift_observation, cursor) {
        Err(ViewError::ForeignCursor) => {}
        Err(error) => {
            return Err(io::Error::other(format!(
                "offline old View cursor failed with the wrong typed error: {error}"
            ))
            .into());
        }
        Ok(_) => {
            return Err(io::Error::other(
                "offline old View cursor was accepted against the drift capture",
            )
            .into());
        }
    }
    println!(
        "offline replay verified linked positive and failed Flow records; baseline View pages: {} then {}, drift result rows: 4",
        first_page.rows().len(),
        second_page.rows().len()
    );
    if rerun_ref.document() == record_ref.document()
        || drift_ref.document() == rerun_ref.document()
        || drift_ref.document() == record_ref.document()
    {
        return Err(io::Error::other("linked records reused an Archive document identity").into());
    }
    Ok(())
}

fn automation_context(
    effective_policy_identity: &str,
    session_policy: SessionPolicy,
    parent: Option<AutomationRecordRef>,
) -> AutomationContext {
    AutomationContext {
        effective_policy_identity: effective_policy_identity.to_owned(),
        session_policy,
        provider: "voidcrawl/cdp".to_owned(),
        browser_identity: optional_env("YOSOI_SPIKE_BROWSER_IDENTITY"),
        source_revision: optional_env("YOSOI_SPIKE_SOURCE_REVISION"),
        parent,
    }
}

fn effective_policy_identity(policy: &Policy) -> Result<String, Box<dyn Error>> {
    let identity = policy.effective_identity()?;
    Ok(format!("v{}:{}", identity.version(), identity.digest()))
}

fn optional_env(name: &str) -> Option<String> {
    env::var(name).ok().filter(|value| !value.trim().is_empty())
}

fn read_record_ref(path: PathBuf) -> Result<AutomationRecordRef, Box<dyn Error>> {
    let encoded = fs::read(path)?;
    Ok(serde_json::from_slice(&encoded)?)
}

fn validate_context(
    record: &AutomationRecord,
    effective_policy_identity: &str,
    session_policy: &SessionPolicy,
    expected_parent: Option<&AutomationRecordRef>,
) -> io::Result<()> {
    let context = record
        .context()
        .ok_or_else(|| io::Error::other("reopened record has no AutomationContext"))?;
    if context.effective_policy_identity != effective_policy_identity
        || context.provider != "voidcrawl/cdp"
        || context.parent.as_ref() != expected_parent
    {
        return Err(io::Error::other(
            "reopened AutomationContext fields changed",
        ));
    }
    let expected_policy = serde_json::to_value(session_policy).map_err(io::Error::other)?;
    let observed_policy =
        serde_json::to_value(&context.session_policy).map_err(io::Error::other)?;
    if expected_policy != observed_policy {
        return Err(io::Error::other("reopened SessionPolicy context changed"));
    }
    Ok(())
}

fn validate_js_record(record: &AutomationRecord) -> io::Result<()> {
    let mut operations = record.operations().iter();
    let value = operations
        .next()
        .ok_or_else(|| io::Error::other("JavaScript record omitted its value receipt"))?;
    let mutation = operations
        .next()
        .ok_or_else(|| io::Error::other("JavaScript record omitted its mutation receipt"))?;
    let script_error = operations
        .next()
        .ok_or_else(|| io::Error::other("JavaScript record omitted its exception receipt"))?;
    if operations.next().is_some()
        || value.kind != "evaluate"
        || value.status != OperationStatus::Observed
        || value.result.as_ref() != Some(&serde_json::json!(42))
        || mutation.kind != "evaluate"
        || mutation.status != OperationStatus::Observed
        || mutation.result.as_ref() != Some(&serde_json::json!("recorded"))
        || script_error.kind != "evaluate"
        || script_error.status != OperationStatus::Unknown
        || script_error.error.is_none()
    {
        return Err(io::Error::other(
            "archived JavaScript value, mutation, or exception receipt changed",
        ));
    }
    Ok(())
}

fn validate_flow_artifact<'a>(
    outcome: &'a FlowOutcome,
    expected: &Flow,
    expected_url: &str,
) -> io::Result<&'a yosoi::automation_record::Observation> {
    if !matches!(outcome.version, 1 | 2 | 3) || outcome.terminal != FlowTermination::Completed {
        return Err(io::Error::other(
            "archived Flow outcome is not a supported completed record",
        ));
    }
    if outcome.flow.failure_capture_policy() != expected.failure_capture_policy() {
        return Err(io::Error::other(
            "archived Flow failure-capture policy changed",
        ));
    }
    let expected_length = expected.steps.len().saturating_add(1);
    if outcome.flow.steps.len() != expected_length
        || outcome.steps.len() != outcome.flow.steps.len()
    {
        return Err(io::Error::other(
            "archived Flow definition or step count changed",
        ));
    }
    let Some(Step::Navigate { url }) = outcome.flow.steps.first() else {
        return Err(io::Error::other(
            "managed Flow is missing its initial Navigate step",
        ));
    };
    if outcome
        .flow
        .steps
        .iter()
        .skip(1)
        .zip(expected.steps.iter())
        .any(|(observed, expected)| observed != expected)
    {
        return Err(io::Error::other("archived typed Flow steps changed"));
    }
    for (position, step) in outcome.steps.iter().enumerate() {
        let expected_index = u64::try_from(position)
            .map_err(|_| io::Error::other("archived Flow step index overflowed"))?;
        if step.index != expected_index
            || !flow_path_matches_version(step, outcome.version, expected_index)
            || step.receipt.status != OperationStatus::Observed
        {
            return Err(io::Error::other(
                "archived Flow receipt order or status changed",
            ));
        }
    }
    let observation = outcome
        .steps
        .iter()
        .rev()
        .find_map(|step| step.receipt.observation.as_ref())
        .filter(|observation| observation.html.is_some())
        .ok_or_else(|| io::Error::other("reopened Flow has no HTML observation"))?;
    if url.as_str() != expected_url
        || observation.url.as_deref() != Some(expected_url)
        || observation.screenshot.is_none()
    {
        return Err(io::Error::other(
            "archived Flow source URL or screenshot changed",
        ));
    }
    Ok(observation)
}

fn validate_drift_artifact<'a>(
    outcome: &'a FlowOutcome,
    expected: &Flow,
    expected_url: &str,
) -> io::Result<&'a yosoi::automation_record::Observation> {
    if outcome.version != 3 || outcome.terminal != FlowTermination::CompletedWithIssues {
        return Err(io::Error::other(
            "drift Flow outcome did not finish with retained issues",
        ));
    }
    if outcome.flow.failure_capture_policy() != FailureCapturePolicy::Screenshot {
        return Err(io::Error::other(
            "drift Flow did not request a post-failure screenshot",
        ));
    }
    if outcome.flow.steps.len() != expected.steps.len().saturating_add(1)
        || outcome.steps.len() != outcome.flow.steps.len()
    {
        return Err(io::Error::other(
            "drift Flow did not retain every executed step",
        ));
    }
    let Some(Step::Navigate { url }) = outcome.flow.steps.first() else {
        return Err(io::Error::other(
            "drift Flow is missing its initial Navigate step",
        ));
    };
    if url.as_str() != expected_url
        || outcome
            .flow
            .steps
            .iter()
            .skip(1)
            .zip(expected.steps.iter())
            .any(|(observed, expected)| observed != expected)
    {
        return Err(io::Error::other("drift Flow URL or typed steps changed"));
    }
    let failed_position = outcome
        .steps
        .iter()
        .position(|step| {
            step.receipt.kind == "assert" && step.receipt.status == OperationStatus::Rejected
        })
        .ok_or_else(|| io::Error::other("drift Flow omitted its failed assertion"))?;
    for (position, step) in outcome.steps.iter().enumerate() {
        if position == failed_position {
            continue;
        }
        let expected_index = u64::try_from(position)
            .map_err(|_| io::Error::other("drift Flow step index overflowed"))?;
        if step.index != expected_index
            || !flow_path_matches_version(step, outcome.version, expected_index)
            || step.receipt.status != OperationStatus::Observed
        {
            return Err(io::Error::other(
                "drift Flow receipt order around the failed assertion changed",
            ));
        }
    }
    let failed = outcome
        .steps
        .get(failed_position)
        .ok_or_else(|| io::Error::other("drift Flow omitted its failed assertion"))?;
    let expected_index = u64::try_from(failed_position)
        .map_err(|_| io::Error::other("drift assertion index overflowed"))?;
    let expected_result = serde_json::json!({
        "passed": false,
        "expected": {
            "kind": "count_at_least",
            "selector": ".row",
            "count": 12
        },
        "actual": 4
    });
    if failed.index != expected_index
        || !flow_path_matches_version(failed, outcome.version, expected_index)
        || failed.receipt.kind != "assert"
        || failed.receipt.status != OperationStatus::Rejected
        || failed.failure != Some(yosoi::flow::FlowFailureCause::Rejected)
        || failed.receipt.result.as_ref() != Some(&expected_result)
    {
        return Err(io::Error::other(
            "drift Flow did not retain the typed rejected count assertion",
        ));
    }
    if outcome.steps.last().is_none_or(|step| {
        step.receipt.kind != "screenshot" || step.receipt.status != OperationStatus::Observed
    }) {
        return Err(io::Error::other(
            "continuation did not run the screenshot after the failed assertion",
        ));
    }
    let observation = failed
        .receipt
        .observation
        .as_ref()
        .filter(|observation| observation.html.is_some())
        .ok_or_else(|| io::Error::other("failed drift assertion has no HTML observation"))?;
    if observation.url.as_deref() != Some(expected_url) {
        return Err(io::Error::other("drift observation URL changed"));
    }
    validate_failure_screenshot_receipt(outcome)?;
    Ok(observation)
}

fn flow_path_matches_version(step: &yosoi::flow::StepOutcome, version: u32, index: u64) -> bool {
    match version {
        1 => step.flow_path.is_empty(),
        2 => step.flow_path.len() == 1 && step.flow_path.first() == Some(&index),
        3 => step.flow_path.as_slice() == &[index],
        _ => false,
    }
}

fn validate_failure_screenshot_receipt(outcome: &FlowOutcome) -> io::Result<()> {
    let receipt = outcome
        .failure_capture
        .as_ref()
        .ok_or_else(|| io::Error::other("failed Flow has no post-failure screenshot receipt"))?;
    match (receipt.kind.as_str(), receipt.status) {
        ("screenshot", OperationStatus::Observed) => {
            if !receipt
                .observation
                .as_ref()
                .is_some_and(|observation| observation.screenshot.is_some())
            {
                return Err(io::Error::other(
                    "observed failure screenshot receipt has no screenshot bytes",
                ));
            }
        }
        ("screenshot", OperationStatus::Unknown | OperationStatus::Rejected) => {}
        ("failure_capture:screenshot", OperationStatus::Unknown | OperationStatus::Rejected)
            if receipt.error.is_some() => {}
        _ => {
            return Err(io::Error::other(
                "post-failure screenshot receipt has an unexpected kind or status",
            ));
        }
    }
    Ok(())
}

fn flow_navigation_url(flow: &Flow) -> io::Result<&str> {
    match flow.steps.first() {
        Some(Step::Navigate { url }) => Ok(url),
        _ => Err(io::Error::other(
            "archived Flow is missing its initial Navigate step",
        )),
    }
}

fn flow_observation(outcome: &FlowOutcome) -> io::Result<&yosoi::automation_record::Observation> {
    outcome
        .steps
        .iter()
        .rev()
        .find_map(|step| step.receipt.observation.as_ref())
        .filter(|observation| observation.html.is_some())
        .ok_or_else(|| io::Error::other("Flow has no HTML observation"))
}

fn browser_policy() -> Result<Policy, Box<dyn Error>> {
    let mut policy = Policy::default();
    policy.page = Page::new(vec![
        Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
    ])?;
    Ok(policy)
}

fn navigating_flow(url: &str, recipe: &Flow) -> Flow {
    flow::new(std::iter::once(action::navigate(url)).chain(recipe.steps().iter().cloned()))
        .with_failure_capture(recipe.failure_capture_policy())
}

fn passing_flow() -> Flow {
    flow::new([
        action::wait(50),
        action::click("#advance"),
        action::enter_text("#query", "shared fixture input"),
        action::wait_until(
            Condition::Visible {
                selector: "#status.ready".to_owned(),
            },
            5_000,
        ),
        action::assert(Condition::Exists {
            selector: "#status.ready".to_owned(),
        })
        .into(),
        action::assert(Condition::CountAtLeast {
            selector: ".row".to_owned(),
            count: 12,
        })
        .into(),
        action::screenshot(),
    ])
    .with_failure_capture(FailureCapturePolicy::Screenshot)
}

fn require_terminal(outcome: &FlowOutcome, expected: FlowTermination) -> io::Result<()> {
    if outcome.terminal == expected {
        Ok(())
    } else {
        Err(io::Error::other(format!(
            "Flow terminal was {:?}, expected {expected:?}",
            outcome.terminal
        )))
    }
}

fn has_screenshot(outcome: &FlowOutcome) -> bool {
    outcome.steps.iter().any(|step| {
        step.receipt
            .observation
            .as_ref()
            .is_some_and(|observation| observation.screenshot.is_some())
    })
}

fn has_completed_browser_document(response: &request::Response) -> bool {
    response.attempts().any(|attempt| {
        matches!(
            attempt.acquisition(),
            yosoi::policy::AcquisitionKind::Browser { .. }
        ) && attempt.state() == AttemptState::Completed
            && attempt.documents().any(|document| {
                document.requested() == DocumentRequest::RenderedDom
                    && matches!(document.outcome(), request::DocumentOutcome::Produced(_))
            })
    })
}

fn require_request_event_for_response(
    event: &OperationReceipt,
    response: &request::Response,
) -> io::Result<()> {
    let expected_result = serde_json::json!({
        "request_id": response.request_id().to_string(),
        "capture_ids": response.attempts().map(|attempt| attempt.capture_id().to_string()).collect::<Vec<_>>(),
        "attempts": 1,
        "completed": 1,
        "documents": 1,
        "produced": 1,
        "all_completed": true
    });
    let event_url = event
        .observation
        .as_ref()
        .and_then(|observation| observation.url.as_deref());
    if event.kind != "request"
        || event.status != OperationStatus::Observed
        || event.result.as_ref() != Some(&expected_result)
        || response.requested_target() != event_url.unwrap_or_default()
    {
        return Err(io::Error::other(
            "watcher request receipt did not match the completed response target and counts",
        ));
    }
    Ok(())
}

fn rendered_dom_document(response: &request::Response) -> Option<DocumentRef<'_>> {
    response
        .attempts()
        .flat_map(|attempt| attempt.documents())
        .find_map(|document| {
            if document.requested() != DocumentRequest::RenderedDom {
                return None;
            }
            match document.outcome() {
                request::DocumentOutcome::Produced(document) => Some(document),
                _ => None,
            }
        })
}

fn count_document_matches(
    document: DocumentRef<'_>,
    selector: &str,
) -> Result<usize, Box<dyn Error>> {
    let plan = Plan::new([output("retained_rows", css(selector)?.node())?])?;
    match document.locate(&plan) {
        LocateOutcome::Matched { result } => Ok(result.findings().len()),
        LocateOutcome::NoMatch { .. } => Ok(0),
        LocateOutcome::Indeterminate { reason_code, .. } => Err(io::Error::other(format!(
            "retained Document locator was indeterminate: {reason_code}"
        ))
        .into()),
        LocateOutcome::Failed { failure } => {
            Err(io::Error::other(format!("retained Document locator failed: {failure:?}")).into())
        }
    }
}

fn require_same_event(expected: &OperationReceipt, observed: &OperationReceipt) -> io::Result<()> {
    if expected.id == observed.id {
        Ok(())
    } else {
        Err(io::Error::other(
            "watcher received a different operation receipt",
        ))
    }
}

#[derive(Debug)]
pub(crate) struct LocalFixture {
    pub(crate) url: String,
    shutdown: Option<oneshot::Sender<()>>,
    task: JoinHandle<io::Result<()>>,
}

impl LocalFixture {
    pub(crate) async fn start() -> io::Result<Self> {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await?;
        let address = listener.local_addr()?;
        let body: Arc<str> = fixture_html()?.into();
        let (shutdown, mut shutdown_rx) = oneshot::channel();
        let task = tokio::spawn(async move {
            let mut connections = JoinSet::new();
            let capacity = Arc::new(tokio::sync::Semaphore::new(64));
            loop {
                tokio::select! {
                    biased;
                    _ = &mut shutdown_rx => break,
                    accepted = listener.accept() => {
                        let (stream, _) = accepted?;
                        let Ok(permit) = Arc::clone(&capacity).try_acquire_owned() else { continue; };
                        let body = Arc::clone(&body);
                        connections.spawn(async move {
                            let _permit = permit;
                            // Browser preconnect/abandonment is local to this connection.
                            let _ = serve_fixture(stream, body.as_bytes()).await;
                        });
                    }
                    Some(_) = connections.join_next(), if !connections.is_empty() => {},
                }
            }
            connections.abort_all();
            while connections.join_next().await.is_some() {}
            Ok(())
        });
        Ok(Self {
            url: format!("http://{address}/"),
            shutdown: Some(shutdown),
            task,
        })
    }

    pub(crate) async fn shutdown(mut self) -> Result<(), Box<dyn Error>> {
        if let Some(shutdown) = self.shutdown.take() {
            let _ = shutdown.send(());
        }
        self.task.await??;
        Ok(())
    }
}

async fn serve_fixture(mut stream: TcpStream, body: &[u8]) -> io::Result<()> {
    let mut request = [0_u8; 4_096];
    let read = tokio::time::timeout(Duration::from_secs(5), stream.read(&mut request))
        .await
        .map_err(|_| {
            io::Error::new(io::ErrorKind::TimedOut, "local fixture request timed out")
        })??;
    if read == 0 {
        return Ok(());
    }
    let response_head = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream.write_all(response_head.as_bytes()).await?;
    stream.write_all(body).await?;
    stream.shutdown().await
}

fn fixture_html() -> io::Result<String> {
    let fixture = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .ok_or_else(|| {
            io::Error::other("SDK example manifest is not under the workspace crates directory")
        })?
        .join("spikes/browser-automation/fixtures/session-flow.html");
    fs::read_to_string(fixture)
}
