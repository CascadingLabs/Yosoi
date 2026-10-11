use serde_json::{Value, json};
use std::{
    error::Error,
    fs,
    path::PathBuf,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio_util::sync::CancellationToken;
use yosoi::{
    Archive,
    automation_record::{AutomationRecord, OperationReceipt, OperationStatus},
    flow::{
        Continuation, Flow, FlowFailureCause, FlowOutcome, FlowPolicy, FlowStopCause,
        FlowStopReason, FlowTermination, SkippedStep, Step, StepOutcome, StopScope,
    },
    policy::Policy,
};

#[test]
fn continuation_policy_and_flow_definitions_round_trip_and_keep_legacy_defaults() {
    let continuation = Continuation::Stop(StopScope::Invocation);
    let mut policy = Policy::default();
    policy.flow.on_failure = continuation;

    let wire = serde_json::to_value(&policy).expect("policy should serialize");
    let reopened: Policy = serde_json::from_value(wire.clone()).expect("policy should reopen");
    assert_eq!(reopened, policy);
    assert_eq!(
        wire["flow"]["on_failure"],
        json!({"kind": "stop", "scope": "invocation"})
    );
    assert_eq!(
        Policy::default().flow.on_failure,
        Continuation::Continue,
        "new Policy values must preserve the historical continue behavior"
    );

    // Policy documents written before FlowPolicy existed inherit its defaults.
    let mut legacy_policy = wire;
    legacy_policy
        .as_object_mut()
        .expect("policy serialization should be an object")
        .remove("flow");
    let legacy_policy: Policy =
        serde_json::from_value(legacy_policy).expect("legacy policy should reopen");
    assert_eq!(legacy_policy.flow, FlowPolicy::default());

    let flow = Flow::new([
        Step::Screenshot.on_failure(Continuation::Continue),
        Flow::new([Step::Wait { milliseconds: 1 }])
            .on_cancellation(Continuation::Stop(StopScope::CurrentFlow))
            .into(),
    ])
    .on_failure(continuation)
    .on_cancellation(Continuation::Continue);
    let flow_wire = serde_json::to_value(&flow).expect("flow should serialize");
    let reopened: Flow = serde_json::from_value(flow_wire).expect("flow should reopen");
    assert_eq!(reopened, flow);
}

#[test]
fn old_policy_identity_projections_reject_unrepresented_continuation_behavior() {
    let baseline = Policy::default();
    let mut changed = Policy::default();
    changed.flow.on_cancellation = Continuation::Stop(StopScope::CurrentFlow);

    assert_ne!(
        baseline.effective_identity().expect("baseline identity"),
        changed.effective_identity().expect("changed identity")
    );
    assert!(changed.archived_v6_identity().is_err());
    assert!(changed.archived_v2_identity().is_err());
    assert!(changed.archived_v3_map_identity().is_err());
    assert!(changed.archived_v3_map_pre_robots_identity().is_err());
    assert!(changed.archived_v5_identity().is_err());
    assert!(
        changed
            .effective_policy()
            .expect("changed effective policy")
            .archived_v4_search_pre_robots_identity()
            .is_err()
    );
}

#[test]
fn legacy_flow_microsecond_fields_remain_microseconds_and_unknown_versions_fail() {
    let legacy: Flow = serde_json::from_value(json!({
        "schema_version": 1,
        "timeout_us": 17,
        "steps": [{
            "kind": "timed",
            "action": {"kind": "wait", "milliseconds": 1},
            "timeout_us": 23
        }]
    }))
    .expect("legacy Flow timeout_us fields should reopen");

    let encoded = serde_json::to_value(&legacy).expect("legacy flow should serialize forward");
    assert_eq!(
        encoded["timeout"],
        serde_json::to_value(Duration::from_micros(17)).expect("duration should serialize")
    );
    assert_eq!(
        encoded["steps"][0]["timeout"],
        serde_json::to_value(Duration::from_micros(23)).expect("duration should serialize")
    );
    let reopened: Flow = serde_json::from_value(encoded).expect("forward flow should reopen");
    assert_eq!(reopened, legacy);

    let unsupported = serde_json::from_value::<Flow>(json!({
        "schema_version": 99,
        "steps": []
    }));
    assert!(unsupported.is_err());

    // An old root version cannot hide a new Step-local override in its tree.
    let legacy_with_override = serde_json::from_value::<Flow>(json!({
        "schema_version": 2,
        "steps": [{
            "kind": "configured",
            "action": {"kind": "screenshot"},
            "on_failure": {"kind": "continue"}
        }]
    }));
    assert!(legacy_with_override.is_err());

    let legacy_with_runtime_binding = serde_json::from_value::<Flow>(json!({
        "schema_version": 2,
        "steps": [{
            "kind": "configured",
            "action": {"kind": "screenshot"},
            "cancellation_binding_required": true
        }]
    }));
    assert!(legacy_with_runtime_binding.is_err());

    // Explicit v3 children retain their own schema boundary under a v2 parent.
    let versioned_child = serde_json::from_value::<Flow>(json!({
        "schema_version": 2,
        "steps": [{
            "kind": "nested_flow",
            "flow": {
                "schema_version": 3,
                "steps": [],
                "on_failure": {"kind": "stop", "scope": "current_flow"}
            }
        }]
    }));
    assert!(versioned_child.is_ok());
}

#[tokio::test]
async fn runtime_cancellation_authority_is_not_serialized_as_replayable() {
    let token = CancellationToken::new();
    let step = Step::Screenshot.with_cancellation(&token);
    let wire = serde_json::to_value(&step).expect("configured step should serialize");
    assert_eq!(wire["cancellation_binding_required"], true);
    assert!(wire.get("cancellation_token").is_none());

    let restored: Step = serde_json::from_value(wire).expect("configured step should deserialize");
    let flow = Flow::new([restored.clone()]);
    assert!(
        flow.validate().is_ok(),
        "deserialized descriptors remain inspectable"
    );
    assert!(matches!(
        flow.invoke().await,
        Err(yosoi::flow::FlowInvokeError::InvalidFlow(
            yosoi::flow::FlowValidationError::UnboundCancellation
        ))
    ));

    let rebound = restored.rebind_cancellation(&token);
    assert!(Flow::new([rebound]).validate().is_ok());
}

#[test]
fn current_flow_and_outcome_schema_preserve_new_continuation_fields() {
    let flow = Flow::new([Step::Screenshot.on_cancellation(Continuation::Continue)])
        .on_failure(Continuation::Stop(StopScope::Invocation));
    let flow_wire = serde_json::to_value(&flow).expect("Flow should serialize");
    assert_eq!(flow_wire["schema_version"], 3);
    assert_eq!(
        flow_wire["on_failure"],
        json!({"kind": "stop", "scope": "invocation"})
    );

    let legacy_outcome: Value = json!({
        "version": 2,
        "flow": {"schema_version": 2, "steps": []},
        "steps": [],
        "terminal": "completed"
    });
    let reopened: yosoi::flow::FlowOutcome =
        serde_json::from_value(legacy_outcome.clone()).expect("legacy outcome should reopen");
    let forwarded = serde_json::to_value(reopened).expect("legacy outcome should serialize");
    assert_eq!(forwarded["version"], 2);
    assert_eq!(forwarded["terminal"], "completed");
    assert!(forwarded.get("continuation_defaults").is_none());
    let reopened: FlowOutcome =
        serde_json::from_value(legacy_outcome).expect("legacy outcome should default policy");
    assert_eq!(reopened.continuation_defaults, FlowPolicy::default());
    assert!(forwarded.get("stop_reason").is_none());
    assert!(forwarded.get("skipped_steps").is_none());
    assert!(forwarded.get("cleanup").is_none());
    assert!(forwarded.get("failure_capture").is_none());
}

#[tokio::test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions report policy archive contract failures."
)]
async fn policy_archive_round_trips_nondefault_flow_behavior() -> Result<(), Box<dyn Error>> {
    let root = unique_temp_path("yosoi-continuation-policy-archive")?;
    fs::create_dir_all(&root)?;
    let archive = Archive::open(&root).await?;
    let mut policy = Policy::default();
    policy.flow.on_failure = Continuation::Stop(StopScope::Invocation);
    let expected_identity = policy.effective_identity()?;
    assert_eq!(expected_identity.version(), 7);

    let reference = archive.write(&policy).await?;
    let reopened: Policy = archive.read(&reference).await?;
    assert_eq!(reopened, policy);
    assert_eq!(reopened.effective_identity()?, expected_identity);

    drop(archive);
    fs::remove_dir_all(&root)?;
    Ok(())
}

#[tokio::test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions report archived continuation contract failures."
)]
async fn archived_outcome_retains_failure_cause_and_scoped_skips() -> Result<(), Box<dyn Error>> {
    let root = unique_temp_path("yosoi-flow-continuation-archive")?;
    fs::create_dir_all(&root)?;
    let archive = Archive::open(&root).await?;
    let child = Flow::new([Step::Screenshot, Step::Screenshot])
        .on_failure(Continuation::Stop(StopScope::CurrentFlow));
    let flow = Flow::new([child.into(), Step::Screenshot]);
    let outcome = FlowOutcome {
        version: 3,
        flow,
        steps: vec![
            StepOutcome {
                index: 0,
                flow_path: vec![0, 0],
                receipt: receipt("continued-failure", OperationStatus::Rejected),
                failure: Some(FlowFailureCause::Rejected),
                cancellation: None,
                cancelled_flow: None,
            },
            StepOutcome {
                index: 1,
                flow_path: vec![1],
                receipt: receipt("parent-sibling", OperationStatus::Observed),
                failure: None,
                cancellation: None,
                cancelled_flow: None,
            },
        ],
        terminal: FlowTermination::CompletedWithIssues,
        continuation_defaults: FlowPolicy::default(),
        stop_reason: None,
        skipped_steps: vec![SkippedStep {
            flow_path: vec![0, 1],
            stopped_by: vec![0, 0],
            cause: FlowStopCause::Failure,
            scope: StopScope::CurrentFlow,
        }],
        cleanup: Vec::new(),
        failure_capture: None,
    };
    assert!(outcome.require_completed().is_err());
    let record = AutomationRecord::new("continuation-record", Vec::new(), Vec::new())?
        .with_flow_outcome(outcome)?;
    let reference = record.write_to(&archive).await?;
    let reopened = AutomationRecord::read_from(&archive, &reference).await?;
    let stored = reopened
        .flow_outcome()
        .ok_or("archived continuation outcome was missing")?;
    assert_eq!(stored.version, 3);
    assert_eq!(stored.terminal, FlowTermination::CompletedWithIssues);
    assert_eq!(stored.steps[0].failure, Some(FlowFailureCause::Rejected));
    assert_eq!(stored.steps[0].receipt.status, OperationStatus::Rejected);
    assert_eq!(stored.skipped_steps.len(), 1);
    assert_eq!(stored.skipped_steps[0].flow_path, [0, 1]);
    assert_eq!(stored.skipped_steps[0].stopped_by, [0, 0]);
    assert!(stored.cleanup.is_empty());

    let global_stop_defaults = FlowPolicy {
        on_failure: Continuation::Stop(StopScope::CurrentFlow),
        on_cancellation: Continuation::Continue,
    };
    let global_stop_child = Flow::new([Step::Screenshot, Step::Screenshot]);
    let global_stop_flow = Flow::new([global_stop_child.into(), Step::Screenshot]);
    let global_stop_outcome = FlowOutcome {
        version: 3,
        flow: global_stop_flow,
        steps: vec![
            StepOutcome {
                index: 0,
                flow_path: vec![0, 0],
                receipt: receipt("global-current-failure", OperationStatus::Rejected),
                failure: Some(FlowFailureCause::Rejected),
                cancellation: None,
                cancelled_flow: None,
            },
            StepOutcome {
                index: 1,
                flow_path: vec![1],
                receipt: receipt("global-current-parent-sibling", OperationStatus::Observed),
                failure: None,
                cancellation: None,
                cancelled_flow: None,
            },
        ],
        terminal: FlowTermination::CompletedWithIssues,
        continuation_defaults: global_stop_defaults,
        stop_reason: None,
        skipped_steps: vec![SkippedStep {
            flow_path: vec![0, 1],
            stopped_by: vec![0, 0],
            cause: FlowStopCause::Failure,
            scope: StopScope::CurrentFlow,
        }],
        cleanup: Vec::new(),
        failure_capture: None,
    };
    let global_stop_record =
        AutomationRecord::new("global-current-record", Vec::new(), Vec::new())?
            .with_flow_outcome(global_stop_outcome)?;
    let global_stop_reference = global_stop_record.write_to(&archive).await?;
    let global_stop_reopened =
        AutomationRecord::read_from(&archive, &global_stop_reference).await?;
    assert_eq!(
        global_stop_reopened
            .flow_outcome()
            .map(|outcome| outcome.continuation_defaults),
        Some(global_stop_defaults)
    );

    let child_cancel = CancellationToken::new();
    let child_flow =
        Flow::new([Step::Screenshot, Step::Screenshot]).on_cancellation(Continuation::Continue);
    let child_step = Step::from(child_flow)
        .with_cancellation(&child_cancel)
        .on_cancellation(Continuation::Continue);
    let cancelled_child =
        Flow::new([child_step, Step::Screenshot]).on_cancellation(Continuation::Continue);
    let child_cancellation_outcome = FlowOutcome {
        version: 3,
        flow: cancelled_child,
        steps: vec![
            StepOutcome {
                index: 0,
                flow_path: vec![0, 0],
                receipt: receipt("child-cancelled", OperationStatus::Rejected),
                failure: None,
                cancellation: Some(yosoi::flow::FlowCancellationCause::Step),
                cancelled_flow: Some(vec![0]),
            },
            StepOutcome {
                index: 1,
                flow_path: vec![1],
                receipt: receipt("parent-after-cancel", OperationStatus::Observed),
                failure: None,
                cancellation: None,
                cancelled_flow: None,
            },
        ],
        terminal: FlowTermination::CompletedWithIssues,
        continuation_defaults: FlowPolicy::default(),
        stop_reason: None,
        skipped_steps: vec![SkippedStep {
            flow_path: vec![0, 1],
            stopped_by: vec![0, 0],
            cause: FlowStopCause::Cancellation,
            scope: StopScope::CurrentFlow,
        }],
        cleanup: Vec::new(),
        failure_capture: None,
    };
    let child_cancellation_record =
        AutomationRecord::new("cancelled-child-record", Vec::new(), Vec::new())?
            .with_flow_outcome(child_cancellation_outcome)?;
    let child_cancellation_reference = child_cancellation_record.write_to(&archive).await?;
    let child_cancellation_reopened =
        AutomationRecord::read_from(&archive, &child_cancellation_reference).await?;
    let child_cancellation_stored = child_cancellation_reopened
        .flow_outcome()
        .ok_or("archived child cancellation outcome was missing")?;
    assert_eq!(
        child_cancellation_stored.steps[0].cancelled_flow,
        Some(vec![0])
    );
    assert_eq!(
        child_cancellation_stored.continuation_defaults,
        FlowPolicy::default()
    );
    assert_eq!(
        child_cancellation_stored.skipped_steps[0].scope,
        StopScope::CurrentFlow
    );

    let cancellation_outcome = FlowOutcome {
        version: 3,
        flow: Flow::new([Step::Screenshot, Step::Screenshot]),
        steps: vec![StepOutcome {
            index: 0,
            flow_path: vec![0],
            receipt: receipt("cancelled-step", OperationStatus::Rejected),
            failure: None,
            cancellation: Some(yosoi::flow::FlowCancellationCause::Invocation),
            cancelled_flow: None,
        }],
        terminal: FlowTermination::Cancelled,
        continuation_defaults: FlowPolicy::default(),
        stop_reason: Some(FlowStopReason {
            flow_path: vec![0],
            cause: FlowStopCause::Cancellation,
            continuation: None,
        }),
        skipped_steps: vec![SkippedStep {
            flow_path: vec![1],
            stopped_by: vec![0],
            cause: FlowStopCause::Cancellation,
            scope: StopScope::Invocation,
        }],
        cleanup: vec![
            OperationReceipt {
                id: "release-success".to_owned(),
                kind: "session.release".to_owned(),
                status: OperationStatus::Observed,
                result: None,
                observation: None,
                error: None,
            },
            OperationReceipt {
                id: "close-failure".to_owned(),
                kind: "session.close".to_owned(),
                status: OperationStatus::Rejected,
                result: None,
                observation: None,
                error: Some("mock close failure".to_owned()),
            },
        ],
        failure_capture: None,
    };
    assert!(cancellation_outcome.require_completed().is_err());
    let cancellation_record =
        AutomationRecord::new("cancelled-cleanup-record", Vec::new(), Vec::new())?
            .with_flow_outcome(cancellation_outcome)?;
    let cancellation_reference = cancellation_record.write_to(&archive).await?;
    let cancellation_reopened =
        AutomationRecord::read_from(&archive, &cancellation_reference).await?;
    let cancellation_stored = cancellation_reopened
        .flow_outcome()
        .ok_or("archived cancelled Flow outcome was missing")?;
    assert_eq!(cancellation_stored.terminal, FlowTermination::Cancelled);
    assert_eq!(
        cancellation_stored.steps[0].cancellation,
        Some(yosoi::flow::FlowCancellationCause::Invocation)
    );
    assert_eq!(cancellation_stored.cleanup.len(), 2);
    assert_eq!(cancellation_stored.cleanup[1].id, "close-failure");
    assert_eq!(
        cancellation_stored.cleanup[1].status,
        OperationStatus::Rejected
    );

    let legacy_outcome: FlowOutcome = serde_json::from_value(json!({
        "version": 2,
        "flow": {"schema_version": 2, "steps": []},
        "steps": [],
        "terminal": "completed"
    }))?;
    let legacy_record =
        AutomationRecord::new("legacy-continuation-record", Vec::new(), Vec::new())?
            .with_flow_outcome(legacy_outcome)?;
    let legacy_reference = legacy_record.write_to(&archive).await?;
    let legacy_reopened = AutomationRecord::read_from(&archive, &legacy_reference).await?;
    let legacy_stored = legacy_reopened
        .flow_outcome()
        .ok_or("archived legacy Flow outcome was missing")?;
    assert_eq!(legacy_stored.version, 2);
    assert_eq!(legacy_stored.continuation_defaults, FlowPolicy::default());
    assert!(legacy_stored.skipped_steps.is_empty());
    assert!(legacy_stored.cleanup.is_empty());

    drop(archive);
    fs::remove_dir_all(&root)?;
    Ok(())
}

#[test]
fn archive_rejects_stops_without_matching_policy_or_cancellation_authority() {
    let default_continue_failure = FlowOutcome {
        version: 3,
        flow: Flow::new([Step::Screenshot, Step::Screenshot]),
        steps: vec![StepOutcome {
            index: 0,
            flow_path: vec![0],
            receipt: receipt("continue-rejected", OperationStatus::Rejected),
            failure: Some(FlowFailureCause::Rejected),
            cancellation: None,
            cancelled_flow: None,
        }],
        terminal: FlowTermination::Failed,
        continuation_defaults: FlowPolicy::default(),
        stop_reason: Some(FlowStopReason {
            flow_path: vec![0],
            cause: FlowStopCause::Failure,
            continuation: Some(Continuation::Stop(StopScope::CurrentFlow)),
        }),
        skipped_steps: vec![SkippedStep {
            flow_path: vec![1],
            stopped_by: vec![0],
            cause: FlowStopCause::Failure,
            scope: StopScope::CurrentFlow,
        }],
        cleanup: Vec::new(),
        failure_capture: None,
    };
    assert!(
        AutomationRecord::new("invalid-default-continue", Vec::new(), Vec::new())
            .and_then(|record| record.with_flow_outcome(default_continue_failure))
            .is_err()
    );

    let child = Flow::new([Step::Screenshot, Step::Screenshot]);
    let global_current_scope_mismatch = FlowOutcome {
        version: 3,
        flow: Flow::new([child.into(), Step::Screenshot]),
        steps: vec![StepOutcome {
            index: 0,
            flow_path: vec![0, 0],
            receipt: receipt("global-current-scope", OperationStatus::Rejected),
            failure: Some(FlowFailureCause::Rejected),
            cancellation: None,
            cancelled_flow: None,
        }],
        terminal: FlowTermination::Failed,
        continuation_defaults: FlowPolicy {
            on_failure: Continuation::Stop(StopScope::CurrentFlow),
            on_cancellation: Continuation::Continue,
        },
        stop_reason: Some(FlowStopReason {
            flow_path: vec![0, 0],
            cause: FlowStopCause::Failure,
            continuation: Some(Continuation::Stop(StopScope::Invocation)),
        }),
        skipped_steps: vec![
            SkippedStep {
                flow_path: vec![0, 1],
                stopped_by: vec![0, 0],
                cause: FlowStopCause::Failure,
                scope: StopScope::Invocation,
            },
            SkippedStep {
                flow_path: vec![1],
                stopped_by: vec![0, 0],
                cause: FlowStopCause::Failure,
                scope: StopScope::Invocation,
            },
        ],
        cleanup: Vec::new(),
        failure_capture: None,
    };
    assert!(
        AutomationRecord::new("invalid-global-scope", Vec::new(), Vec::new())
            .and_then(|record| record.with_flow_outcome(global_current_scope_mismatch))
            .is_err()
    );

    let action_continue_cannot_skip = FlowOutcome {
        version: 3,
        flow: Flow::new([
            Step::Screenshot
                .with_cancellation(&CancellationToken::new())
                .on_cancellation(Continuation::Continue),
            Step::Screenshot,
        ]),
        steps: vec![StepOutcome {
            index: 0,
            flow_path: vec![0],
            receipt: receipt("action-continue-cancelled", OperationStatus::Rejected),
            failure: None,
            cancellation: Some(yosoi::flow::FlowCancellationCause::Step),
            cancelled_flow: None,
        }],
        terminal: FlowTermination::CompletedWithIssues,
        continuation_defaults: FlowPolicy::default(),
        stop_reason: None,
        skipped_steps: vec![SkippedStep {
            flow_path: vec![1],
            stopped_by: vec![0],
            cause: FlowStopCause::Cancellation,
            scope: StopScope::CurrentFlow,
        }],
        cleanup: Vec::new(),
        failure_capture: None,
    };
    assert!(
        AutomationRecord::new("invalid-action-continue-skip", Vec::new(), Vec::new())
            .and_then(|record| record.with_flow_outcome(action_continue_cannot_skip))
            .is_err()
    );

    let unknown_effect_with_cancelled_terminal = FlowOutcome {
        version: 3,
        flow: Flow::new([Step::Screenshot]),
        steps: vec![StepOutcome {
            index: 0,
            flow_path: vec![0],
            receipt: receipt("unknown-effect", OperationStatus::Unknown),
            failure: Some(FlowFailureCause::UnknownOutcome),
            cancellation: Some(yosoi::flow::FlowCancellationCause::Invocation),
            cancelled_flow: None,
        }],
        terminal: FlowTermination::Cancelled,
        continuation_defaults: FlowPolicy::default(),
        stop_reason: Some(FlowStopReason {
            flow_path: vec![0],
            cause: FlowStopCause::Cancellation,
            continuation: None,
        }),
        skipped_steps: Vec::new(),
        cleanup: Vec::new(),
        failure_capture: None,
    };
    assert!(
        AutomationRecord::new("invalid-unknown-cancelled", Vec::new(), Vec::new())
            .and_then(|record| record.with_flow_outcome(unknown_effect_with_cancelled_terminal))
            .is_err()
    );

    let unknown_then_observed = FlowOutcome {
        version: 3,
        flow: Flow::new([Step::Screenshot, Step::Screenshot]),
        steps: vec![
            StepOutcome {
                index: 0,
                flow_path: vec![0],
                receipt: receipt("unknown-hard-stop", OperationStatus::Unknown),
                failure: Some(FlowFailureCause::UnknownOutcome),
                cancellation: None,
                cancelled_flow: None,
            },
            StepOutcome {
                index: 1,
                flow_path: vec![1],
                receipt: receipt("observed-after-unknown", OperationStatus::Observed),
                failure: None,
                cancellation: None,
                cancelled_flow: None,
            },
        ],
        terminal: FlowTermination::CompletedWithIssues,
        continuation_defaults: FlowPolicy::default(),
        stop_reason: None,
        skipped_steps: Vec::new(),
        cleanup: Vec::new(),
        failure_capture: None,
    };
    assert!(
        AutomationRecord::new("invalid-unknown-then-observed", Vec::new(), Vec::new())
            .and_then(|record| record.with_flow_outcome(unknown_then_observed))
            .is_err()
    );

    let child_token = CancellationToken::new();
    let child_step = Step::from(Flow::new([Step::Screenshot])).with_cancellation(&child_token);
    let root_cancel_with_forged_child_authority = FlowOutcome {
        version: 3,
        flow: Flow::new([child_step]),
        steps: vec![StepOutcome {
            index: 0,
            flow_path: vec![0, 0],
            receipt: receipt("root-cancelled-child", OperationStatus::Rejected),
            failure: None,
            cancellation: Some(yosoi::flow::FlowCancellationCause::Invocation),
            cancelled_flow: Some(vec![0]),
        }],
        terminal: FlowTermination::Cancelled,
        continuation_defaults: FlowPolicy::default(),
        stop_reason: Some(FlowStopReason {
            flow_path: vec![0, 0],
            cause: FlowStopCause::Cancellation,
            continuation: None,
        }),
        skipped_steps: Vec::new(),
        cleanup: Vec::new(),
        failure_capture: None,
    };
    assert!(
        AutomationRecord::new(
            "invalid-root-cancelled-child-authority",
            Vec::new(),
            Vec::new()
        )
        .and_then(|record| record.with_flow_outcome(root_cancel_with_forged_child_authority))
        .is_err()
    );
}

#[tokio::test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions report legacy outcome compatibility failures."
)]
async fn legacy_failed_cancelled_and_unknown_outcomes_archive_without_new_causes()
-> Result<(), Box<dyn Error>> {
    let root = unique_temp_path("yosoi-legacy-flow-outcomes")?;
    fs::create_dir_all(&root)?;
    let archive = Archive::open(&root).await?;
    let cases = [
        ("failed", "rejected", FlowTermination::Failed),
        ("cancelled", "rejected", FlowTermination::Cancelled),
        ("unknown", "unknown", FlowTermination::Unknown),
    ];

    for version in [1_u32, 2_u32] {
        for (label, receipt_status, terminal) in cases {
            let path = if version == 1 { json!([]) } else { json!([0]) };
            let value = json!({
                "version": version,
                "flow": {
                    "schema_version": version,
                    "steps": [{"kind": "screenshot"}]
                },
                "steps": [{
                    "index": 0,
                    "flow_path": path,
                    "receipt": {
                        "id": format!("legacy-{version}-{label}-receipt"),
                        "kind": "screenshot",
                        "status": receipt_status,
                        "result": null,
                        "observation": null,
                        "error": null
                    }
                }],
                "terminal": label
            });
            let outcome: FlowOutcome = serde_json::from_value(value)?;
            assert_eq!(outcome.continuation_defaults, FlowPolicy::default());
            assert_eq!(outcome.steps[0].failure, None);
            assert_eq!(outcome.steps[0].cancellation, None);

            let record = AutomationRecord::new(
                format!("legacy-{version}-{label}-record"),
                Vec::new(),
                Vec::new(),
            )?
            .with_flow_outcome(outcome)?;
            let reference = record.write_to(&archive).await?;
            let reopened = AutomationRecord::read_from(&archive, &reference).await?;
            let stored = reopened
                .flow_outcome()
                .ok_or("archived legacy outcome was missing")?;
            assert_eq!(stored.version, version);
            assert_eq!(stored.terminal, terminal);
            assert_eq!(stored.steps[0].failure, None);
            assert_eq!(stored.steps[0].cancellation, None);
            assert_eq!(stored.continuation_defaults, FlowPolicy::default());
        }
    }

    drop(archive);
    fs::remove_dir_all(&root)?;
    Ok(())
}

fn receipt(id: &str, status: OperationStatus) -> OperationReceipt {
    OperationReceipt {
        id: id.to_owned(),
        kind: "screenshot".to_owned(),
        status,
        result: None,
        observation: None,
        error: (status == OperationStatus::Rejected).then(|| "mock rejection".to_owned()),
    }
}

fn unique_temp_path(prefix: &str) -> Result<PathBuf, Box<dyn Error>> {
    let nanos = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    Ok(std::env::temp_dir().join(format!("{prefix}-{}-{nanos}", std::process::id())))
}
