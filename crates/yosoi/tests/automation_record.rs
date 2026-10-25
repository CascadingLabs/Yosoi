use std::env as std_env;
use std::error::Error;
use std::fs;
use std::path::PathBuf;
use std::process as std_process;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};
use yosoi::browser as browser_config;
use yosoi::flow as yosoi_flow;
use yosoi::session as yosoi_session;

use yosoi::Archive;
use yosoi::automation_record::{
    AutomationRecord, AutomationRecordError, AutomationRecordRef, Observation, OperationReceipt,
    OperationStatus,
};
use yosoi::flow::{Flow, FlowOutcome, FlowTermination, Step, StepOutcome};

const CHILD_ROOT_ENV: &str = "YOSOI_AUTOMATION_RECORD_CHILD_ROOT";
const CHILD_REFERENCE_ENV: &str = "YOSOI_AUTOMATION_RECORD_CHILD_REFERENCE";

#[tokio::test]
#[expect(clippy::panic_in_result_fn, reason = "archive contract assertions")]
async fn optional_engine_identity_and_unknown_effect_survive_offline_round_trip()
-> Result<(), Box<dyn Error>> {
    let identity: browser_config::BrowserExecutionIdentity = serde_json::from_value(
        serde_json::json!({
            "engine":"moli","protocol":"bidi","process_owned":false,
            "controller_version":"0.4.0","capability_profile":"com.cascadinglabs.yosoi.bidi.moli.layout.v1",
            "reported_name":null,"reported_version":null,"executable_version":null,"executable_sha256":null,
            "moli_profile":"layout","moli_resources":true,"owned_moli_private_network_blocking":null
        }),
    )?;
    let mut captured = observation();
    captured.browser = Some(identity.clone());
    let receipt = OperationReceipt {
        browser: Some(identity.clone()),
        id: "native-unknown-1".to_owned(),
        kind: "click".to_owned(),
        status: OperationStatus::Unknown,
        result: None,
        observation: Some(captured.clone()),
        error: Some("connection lost after possible dispatch".to_owned()),
    };
    let record = AutomationRecord::new(
        "native-evidence",
        vec![captured.clone()],
        vec![receipt.clone()],
    )?;
    let directory = unique_temp_path("yosoi-bidi-record")?;
    let archive = Archive::open(&directory).await?;
    let reference = record.write_to(&archive).await?;
    drop(archive);
    let reopened = Archive::open(&directory).await?;
    let restored = AutomationRecord::read_from(&reopened, &reference).await?;
    assert_eq!(
        restored
            .observations()
            .first()
            .ok_or("missing observation")?
            .browser
            .as_ref(),
        Some(&identity)
    );
    let operation = restored.operations().first().ok_or("missing receipt")?;
    assert_eq!(operation.browser.as_ref(), Some(&identity));
    assert_eq!(operation.status, OperationStatus::Unknown);
    assert!(operation.browser.as_ref().is_some_and(
        |browser| browser.reported_version.is_none() && browser.executable_sha256.is_none()
    ));
    let mut contradictory = receipt;
    contradictory.browser = Some(browser_config::BrowserExecutionIdentity {
        engine: browser_config::BrowserEngine::Firefox,
        ..identity
    });
    assert!(matches!(
        AutomationRecord::new("contradictory", vec![captured], vec![contradictory]),
        Err(AutomationRecordError::BrowserProvenanceMismatch)
    ));
    drop(reopened);
    fs::remove_dir_all(directory)?;
    Ok(())
}

#[test]
#[expect(clippy::panic_in_result_fn, reason = "legacy serialization assertions")]
fn legacy_observations_do_not_gain_an_invented_browser() -> Result<(), Box<dyn Error>> {
    let legacy = serde_json::to_value(observation())?;
    assert!(legacy.get("browser").is_none());
    let decoded: Observation = serde_json::from_value(legacy.clone())?;
    assert!(decoded.browser.is_none());
    assert_eq!(serde_json::to_value(decoded)?, legacy);
    Ok(())
}

fn observation() -> Observation {
    Observation {
        browser: None,
        id: "observation-1".to_owned(),
        session_id: "session-1".to_owned(),
        tab_id: "tab-1".to_owned(),
        document_epoch: 7,
        html: Some("<main><h1>Offline</h1></main>".to_owned()),
        url: Some("https://example.test/".to_owned()),
        screenshot: Some(vec![0x89, 0x50, 0x4e, 0x47]),
    }
}

#[tokio::test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions report persistence contract failures."
)]
async fn archived_record_reference_reopens_in_a_fresh_process() -> Result<(), Box<dyn Error>> {
    if std_env::var_os(CHILD_ROOT_ENV).is_some() {
        return Ok(());
    }

    let root = unique_temp_path("yosoi-automation-record")?;
    fs::create_dir_all(&root)?;
    let reference_path = root.join("automation-record-ref.json");
    let archive = Archive::open(&root).await?;
    let outcome = FlowOutcome {
        failure_capture: None,
        version: 2,
        flow: Flow::new([Flow::new([Step::Navigate {
            url: "https://example.test/".to_owned(),
        }])
        .into()]),
        steps: vec![StepOutcome {
            index: 0,
            flow_path: vec![0, 0],
            receipt: OperationReceipt {
                browser: None,
                id: "flow-operation-1".to_owned(),
                kind: "navigate".to_owned(),
                status: OperationStatus::Observed,
                result: None,
                observation: Some(observation()),
                error: None,
            },
            failure: None,
            cancellation: None,
            cancelled_flow: None,
        }],
        terminal: FlowTermination::Completed,
        continuation_defaults: yosoi_flow::FlowPolicy::default(),
        stop_reason: None,
        skipped_steps: Vec::new(),
        cleanup: Vec::new(),
    };
    let record = AutomationRecord::new(
        "record-1",
        vec![observation()],
        vec![OperationReceipt {
            browser: None,
            id: "operation-1".to_owned(),
            kind: "navigate".to_owned(),
            status: OperationStatus::Observed,
            result: Some(serde_json::json!({"url": "https://example.test/"})),
            observation: Some(observation()),
            error: None,
        }],
    )?
    .with_flow_outcome(outcome)?;
    let reference = record.write_to(&archive).await?;
    fs::write(&reference_path, serde_json::to_vec(&reference)?)?;
    drop(archive);

    let executable = std_env::current_exe()?;
    let status = Command::new(executable)
        .args([
            "--exact",
            "archived_record_reference_reopens_in_a_fresh_process_child",
            "--nocapture",
        ])
        .env(CHILD_ROOT_ENV, &root)
        .env(CHILD_REFERENCE_ENV, &reference_path)
        .status()?;
    assert!(status.success(), "fresh-process record reopen failed");
    fs::remove_dir_all(&root)?;
    Ok(())
}

#[tokio::test]
async fn archived_record_read_reports_missing_and_corrupt_artifacts() -> Result<(), Box<dyn Error>>
{
    let root = unique_temp_path("yosoi-automation-record-negative")?;
    fs::create_dir_all(&root)?;
    let archive = Archive::open(&root).await?;
    let outcome = FlowOutcome {
        version: 1,
        flow: Flow::new([Step::Navigate {
            url: "https://example.test/".to_owned(),
        }]),
        steps: vec![StepOutcome {
            index: 0,
            flow_path: Vec::new(),
            receipt: OperationReceipt {
                browser: None,
                id: "negative-flow-operation-1".to_owned(),
                kind: "navigate".to_owned(),
                status: OperationStatus::Observed,
                result: None,
                observation: Some(observation()),
                error: None,
            },
            failure: None,
            cancellation: None,
            cancelled_flow: None,
        }],
        terminal: FlowTermination::Completed,
        continuation_defaults: yosoi_flow::FlowPolicy::default(),
        stop_reason: None,
        skipped_steps: Vec::new(),
        cleanup: Vec::new(),
        failure_capture: None,
    };
    let record = AutomationRecord::new(
        "negative-record-1",
        vec![observation()],
        vec![OperationReceipt {
            browser: None,
            id: "negative-operation-1".to_owned(),
            kind: "navigate".to_owned(),
            status: OperationStatus::Observed,
            result: None,
            observation: Some(observation()),
            error: None,
        }],
    )?
    .with_flow_outcome(outcome)?;
    let reference = record.write_to(&archive).await?;

    let mut missing_reference_value = serde_json::to_value(&reference)?;
    let missing_key = yosoi_session::new_operation_id();
    let missing_document = missing_reference_value
        .as_object_mut()
        .and_then(|value| value.get_mut("document"))
        .ok_or("AutomationRecordRef serialization omitted its document reference")?;
    *missing_document = serde_json::Value::String(format!("document:v1:{missing_key}"));
    let missing_reference: AutomationRecordRef = serde_json::from_value(missing_reference_value)?;
    let missing_record_result = AutomationRecord::read_from(&archive, &missing_reference).await;
    if !matches!(
        missing_record_result,
        Err(AutomationRecordError::Archive(message))
            if message.contains("document record") && message.contains("does not exist")
    ) {
        return Err("read_from did not report a typed missing-record error".into());
    }

    let payload_path = document_payload_path(&archive, &reference);
    let mut corrupt_payload = fs::read(&payload_path)?;
    let first_byte = corrupt_payload
        .first_mut()
        .ok_or("archived AutomationRecord payload unexpectedly empty")?;
    *first_byte ^= 0x01;
    fs::write(&payload_path, &corrupt_payload)?;
    let corrupt_result = AutomationRecord::read_from(&archive, &reference).await;
    if !matches!(
        corrupt_result,
        Err(AutomationRecordError::Archive(message))
            if message.contains("wrong SHA-256 digest")
    ) {
        return Err("read_from accepted a tampered record payload".into());
    }

    fs::remove_file(&payload_path)?;
    let missing_payload_result = AutomationRecord::read_from(&archive, &reference).await;
    if !matches!(
        missing_payload_result,
        Err(AutomationRecordError::Archive(message))
            if message.contains("payload does not exist")
    ) {
        return Err("read_from did not report a typed missing-payload error".into());
    }

    drop(archive);
    fs::remove_dir_all(&root)?;
    Ok(())
}

#[tokio::test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions report persistence contract failures."
)]
async fn archived_record_reference_reopens_in_a_fresh_process_child() -> Result<(), Box<dyn Error>>
{
    let (Some(root), Some(reference_path)) = (
        std_env::var_os(CHILD_ROOT_ENV),
        std_env::var_os(CHILD_REFERENCE_ENV),
    ) else {
        return Ok(());
    };
    let reference_bytes = fs::read(reference_path)?;
    let reference: AutomationRecordRef = serde_json::from_slice(&reference_bytes)?;
    let archive = Archive::open(PathBuf::from(root)).await?;
    let record = AutomationRecord::read_from(&archive, &reference).await?;
    assert_eq!(record.id(), "record-1");
    assert_eq!(
        record
            .observations()
            .first()
            .and_then(|item| item.html.as_deref()),
        Some("<main><h1>Offline</h1></main>")
    );
    assert_eq!(
        record.operations().first().map(|item| item.status),
        Some(OperationStatus::Observed)
    );
    assert_eq!(
        record
            .flow_outcome()
            .and_then(|outcome| outcome.steps.first())
            .map(|step| step.index),
        Some(0)
    );
    assert_eq!(
        record
            .flow_outcome()
            .and_then(|outcome| outcome.steps.first())
            .map(|step| step.flow_path.as_slice()),
        Some(&[0, 0][..])
    );
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
fn nested_flow_results_must_be_a_depth_first_path_prefix() -> Result<(), Box<dyn Error>> {
    let flow = Flow::new([
        Step::Screenshot,
        Flow::new([Step::Screenshot, Step::Screenshot]).into(),
        Step::Screenshot,
    ]);

    for paths in [
        vec![vec![0], vec![0]],
        vec![vec![0], vec![1, 1]],
        vec![vec![0], vec![1, 1], vec![1, 0]],
    ] {
        let result = AutomationRecord::new("invalid-paths", Vec::new(), Vec::new())?
            .with_flow_outcome(nested_outcome(flow.clone(), paths, FlowTermination::Failed));
        assert!(matches!(
            result,
            Err(AutomationRecordError::InvalidFlowStepPath)
        ));
    }

    let incomplete =
        AutomationRecord::new("incomplete", Vec::new(), Vec::new())?.with_flow_outcome(
            nested_outcome(flow.clone(), vec![vec![0]], FlowTermination::Completed),
        );
    assert!(matches!(
        incomplete,
        Err(AutomationRecordError::FlowStepCountMismatch)
    ));

    let stopped = AutomationRecord::new("stopped", Vec::new(), Vec::new())?.with_flow_outcome(
        nested_outcome(flow, vec![vec![0], vec![1, 0]], FlowTermination::Failed),
    )?;
    assert_eq!(
        stopped.flow_outcome().map(|outcome| outcome.steps.len()),
        Some(2)
    );
    Ok(())
}

fn nested_outcome(flow: Flow, paths: Vec<Vec<u64>>, terminal: FlowTermination) -> FlowOutcome {
    let last = paths.len().saturating_sub(1);
    FlowOutcome {
        version: 2,
        flow,
        steps: paths
            .into_iter()
            .enumerate()
            .map(|(index, flow_path)| {
                let result_index = u64::try_from(index).unwrap_or(u64::MAX);
                StepOutcome {
                    index: result_index,
                    flow_path,
                    receipt: OperationReceipt {
                        browser: None,
                        id: format!("nested-operation-{index}"),
                        kind: "mock".to_owned(),
                        status: if terminal == FlowTermination::Failed && index == last {
                            OperationStatus::Rejected
                        } else {
                            OperationStatus::Observed
                        },
                        result: None,
                        observation: None,
                        error: None,
                    },
                    failure: None,
                    cancellation: None,
                    cancelled_flow: None,
                }
            })
            .collect(),
        terminal,
        continuation_defaults: yosoi_flow::FlowPolicy::default(),
        stop_reason: None,
        skipped_steps: Vec::new(),
        cleanup: Vec::new(),
        failure_capture: None,
    }
}

fn unique_temp_path(prefix: &str) -> Result<PathBuf, Box<dyn Error>> {
    let nanos = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    Ok(std_env::temp_dir().join(format!("{prefix}-{}-{nanos}", std_process::id())))
}

fn document_payload_path(archive: &Archive, reference: &AutomationRecordRef) -> PathBuf {
    let key = reference.document().logical_key();
    let shard: String = key.chars().take(2).collect();
    archive
        .format_root()
        .join("documents")
        .join(shard)
        .join(key)
        .join("payload.bin")
}
