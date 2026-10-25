use std::error::Error;
use std::io as std_io;
use yosoi::assertions as yosoi_assertions;
use yosoi::flow as yosoi_flow;

use yosoi::{
    action::{self, check},
    assertions::{AssertionGroup, AssertionReport, Check},
    automation_record::{AutomationRecord, Observation, OperationReceipt, OperationStatus},
    contracts::{FieldId, FieldIssue, FieldIssueKind},
    documents::DocumentId,
    expect,
    flow::{
        Flow, FlowInvokeError, FlowOutcome, FlowPolicy, FlowTermination, FlowValidationError, Step,
        StepOutcome,
    },
    locators::{IncompleteEvidence, LocateOutcome},
    prelude as ys,
    session::{UntilCheck, UntilCheckState, UntilReport, UntilScope, UntilTermination},
};

type TestError = Box<dyn Error + Send + Sync>;

#[test]

fn satisfied_report_with_a_pending_check_is_rejected_by_report_and_record_validation() {
    let mut forged = valid_report();
    forged.checks[0].state = UntilCheckState::Pending;
    forged.checks[0].evidence = None;

    assert!(forged.validate().is_err());
    assert!(record_with_report(forged).is_err());
}

#[test]

fn attached_until_report_must_match_the_receipt_observation_scope() {
    let mut forged = valid_report();
    forged.scope.document_epoch = forged.scope.document_epoch.saturating_add(1);

    assert!(record_with_report(forged).is_err());
}

#[test]

fn satisfied_until_report_requires_frame_and_loader_scope() {
    let mut missing_frame = valid_report();
    missing_frame.scope.frame_id = None;
    assert!(missing_frame.validate().is_err());
    assert!(record_with_report(missing_frame).is_err());

    let mut missing_loader = valid_report();
    missing_loader.scope.loader_id = None;
    assert!(missing_loader.validate().is_err());
    assert!(record_with_report(missing_loader).is_err());
}

#[test]

fn attached_until_step_requires_its_trigger_receipt() {
    let mut forged = valid_report();
    forged.trigger = None;

    assert!(record_with_report(forged).is_err());
}

#[test]

fn satisfied_until_rejects_errorful_trigger_and_trigger_result_without_value() {
    let mut errorful_trigger = valid_report();
    if let Some(trigger) = errorful_trigger.trigger.as_mut() {
        trigger.error = Some("trigger returned an error".to_owned());
    }
    assert!(errorful_trigger.validate().is_err());
    assert!(record_with_report(errorful_trigger).is_err());

    let mut missing_value = valid_report();
    if let Some(trigger) = missing_value.trigger.as_mut() {
        trigger.result = Some(serde_json::json!({"started_at_unix_us": 1_000}));
    }
    assert!(record_with_report(missing_value).is_err());
}

#[test]

fn until_trigger_receipt_identity_must_be_unique_within_the_flow() {
    let mut forged = valid_report();
    if let Some(trigger) = forged.trigger.as_mut() {
        trigger.id = "until-receipt".to_owned();
    }

    assert!(record_with_report(forged).is_err());
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
fn archive_requires_a_matching_nonignored_ax_node() -> Result<(), TestError> {
    let expected = "Ready product row";
    let valid = accessibility_report(expected, expected, "button", false);
    valid.validate()?;
    assert!(record_with_step(valid, accessibility_step(expected), "ax-until").is_ok());

    let ignored_only = accessibility_report(expected, expected, "button", true);
    assert!(record_with_step(ignored_only, accessibility_step(expected), "ax-ignored").is_err());

    let wrong_name = accessibility_report(expected, "Ready other row", "button", false);
    assert!(record_with_step(wrong_name, accessibility_step(expected), "ax-name").is_err());

    let wrong_role = accessibility_report(expected, expected, "checkbox", false);
    assert!(record_with_step(wrong_role, accessibility_step(expected), "ax-role").is_err());
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
fn network_evidence_must_match_the_top_level_loader_epoch_and_trigger_time() -> Result<(), TestError>
{
    let attempt = "catalog-17";
    let valid = network_report(attempt);
    valid.validate()?;
    assert!(record_with_step(valid, network_step(attempt), "network-until").is_ok());

    let mut stale_epoch = network_report(attempt);
    set_check_evidence_value(&mut stale_epoch, "document_epoch", serde_json::json!(6))?;
    assert!(record_with_step(stale_epoch, network_step(attempt), "stale-epoch").is_err());

    let mut subframe = network_report(attempt);
    set_check_evidence_value(&mut subframe, "top_level", serde_json::json!(false))?;
    assert!(record_with_step(subframe, network_step(attempt), "subframe").is_err());

    let mut wrong_frame = network_report(attempt);
    set_check_evidence_value(
        &mut wrong_frame,
        "frame_id",
        serde_json::json!("frame-other"),
    )?;
    assert!(record_with_step(wrong_frame, network_step(attempt), "wrong-frame").is_err());

    let mut wrong_loader = network_report(attempt);
    set_check_evidence_value(
        &mut wrong_loader,
        "loader_id",
        serde_json::json!("loader-other"),
    )?;
    assert!(record_with_step(wrong_loader, network_step(attempt), "wrong-loader").is_err());

    let mut before_trigger = network_report(attempt);
    set_check_evidence_value(
        &mut before_trigger,
        "started_at_unix_us",
        serde_json::json!(999),
    )?;
    assert!(record_with_step(before_trigger, network_step(attempt), "early-response").is_err());

    let mut empty_request_id = network_report(attempt);
    set_check_evidence_value(&mut empty_request_id, "request_id", serde_json::json!(""))?;
    assert!(record_with_step(empty_request_id, network_step(attempt), "empty-request").is_err());

    let mut wrong_body = network_report(attempt);
    set_network_body_attempt(&mut wrong_body, "other-attempt")?;
    assert!(record_with_step(wrong_body, network_step(attempt), "wrong-body").is_err());
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
fn embedded_trigger_identity_cannot_collide_with_a_later_flow_receipt() -> Result<(), TestError> {
    let mut report = valid_report();
    let trigger = report
        .trigger
        .as_mut()
        .ok_or("positive report has no trigger")?;
    trigger.id = "later-flow-receipt".to_owned();
    let encoded_report = serde_json::to_value(report)?;
    let flow = Flow::new([
        action::click("#go").until(expect::visible("#receipt")),
        action::click("#next"),
    ]);
    let outcome = FlowOutcome {
        version: 3,
        flow,
        steps: vec![
            StepOutcome {
                index: 0,
                flow_path: vec![0],
                receipt: until_receipt("until-receipt", encoded_report),
                failure: None,
                cancellation: None,
                cancelled_flow: None,
            },
            StepOutcome {
                index: 1,
                flow_path: vec![1],
                receipt: OperationReceipt {
                    browser: None,
                    id: "later-flow-receipt".to_owned(),
                    kind: "click".to_owned(),
                    status: OperationStatus::Observed,
                    result: None,
                    observation: None,
                    error: None,
                },
                failure: None,
                cancellation: None,
                cancelled_flow: None,
            },
        ],
        terminal: FlowTermination::Completed,
        continuation_defaults: FlowPolicy::default(),
        stop_reason: None,
        skipped_steps: Vec::new(),
        cleanup: Vec::new(),
        failure_capture: None,
    };
    assert!(record_with_outcome(outcome, Vec::new()).is_err());
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
fn a_report_is_bounded_and_many_valid_reports_share_the_record_evidence_budget()
-> Result<(), TestError> {
    let mut oversized = network_report("single-large");
    set_network_padding(&mut oversized, "p".repeat(1_100_000))?;
    assert!(oversized.validate().is_err());
    assert!(record_with_step(oversized, network_step("single-large"), "oversized").is_err());

    let padding = "p".repeat(970_000);
    let mut flow_steps = Vec::new();
    let mut outcomes = Vec::new();
    for index in 0..9_u64 {
        let attempt = format!("record-large-{index}");
        let mut report = network_report(&attempt);
        set_network_padding(&mut report, padding.clone())?;
        assert!(report.validate().is_ok());
        let expected = network_step(&attempt);
        flow_steps.push(expected);
        let report_value = serde_json::to_value(report)?;
        outcomes.push(StepOutcome {
            index,
            flow_path: vec![index],
            receipt: until_receipt(&format!("until-{index}"), report_value),
            failure: None,
            cancellation: None,
            cancelled_flow: None,
        });
    }
    let outcome = FlowOutcome {
        version: 3,
        flow: Flow::new(flow_steps),
        steps: outcomes,
        terminal: FlowTermination::Completed,
        continuation_defaults: FlowPolicy::default(),
        stop_reason: None,
        skipped_steps: Vec::new(),
        cleanup: Vec::new(),
        failure_capture: None,
    };
    assert!(record_with_outcome(outcome, Vec::new()).is_err());
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
fn operations_vector_must_reference_the_same_until_receipt_as_flow_outcome() -> Result<(), TestError>
{
    let attempt = "canonical-operation";
    let canonical_report = network_report(attempt);
    let canonical = record_with_step(canonical_report, network_step(attempt), "until-canonical")?;
    let outcome = canonical
        .flow_outcome()
        .cloned()
        .ok_or("canonical Flow outcome missing")?;
    let canonical_receipt = outcome
        .steps
        .first()
        .map(|step| step.receipt.clone())
        .ok_or("canonical Until receipt missing")?;
    let matching = AutomationRecord::new(
        "matching-until-record",
        Vec::new(),
        vec![canonical_receipt.clone()],
    )?
    .with_flow_outcome(outcome.clone());
    assert!(matching.is_ok());

    let mut inconsistent = network_report("different-payload");
    if let Some(check) = inconsistent.checks.first_mut()
        && let Some(evidence) = check.evidence.as_mut()
        && let Some(body) = evidence
            .get_mut("body")
            .and_then(serde_json::Value::as_object_mut)
    {
        body.insert("attempt".to_owned(), serde_json::json!("different-payload"));
    }
    let inconsistent_receipt =
        until_receipt(&canonical_receipt.id, serde_json::to_value(inconsistent)?);
    let mismatched = AutomationRecord::new(
        "mismatched-until-record",
        Vec::new(),
        vec![inconsistent_receipt],
    )?
    .with_flow_outcome(outcome);
    assert!(mismatched.is_err());
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
fn a_well_scoped_until_report_is_accepted_by_the_public_record_model() -> Result<(), TestError> {
    let report = valid_report();
    report.validate()?;
    let record = record_with_report(report)?;
    assert_eq!(
        record
            .flow_outcome()
            .and_then(|outcome| outcome.steps.first())
            .map(|step| step.receipt.kind.as_str()),
        Some("until")
    );
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
fn until_flow_serialization_selects_schema_four_and_rejects_legacy_relabeling()
-> Result<(), TestError> {
    let flow = Flow::new([action::click("#go").until(expect::visible("#receipt"))]);
    let mut encoded = serde_json::to_value(&flow)?;
    assert_eq!(encoded["schema_version"], 4);

    encoded["schema_version"] = serde_json::json!(3);
    assert!(serde_json::from_value::<Flow>(encoded).is_err());

    let ordinary = Flow::new([action::click("#go")]);
    assert_eq!(serde_json::to_value(ordinary)?["schema_version"], 3);
    Ok(())
}

#[tokio::test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn deserialized_local_contract_until_is_rejected_before_session_acquisition()
-> Result<(), TestError> {
    let step = action::assert_all::<UntilModelContract>(
        UntilModelContract::plan()?,
        [check(|contract: &UntilModelContract| {
            contract.value == "ready"
        })],
    )
    .until();
    let authored = Flow::new([step]);
    let encoded = serde_json::to_vec(&authored)?;
    let restored: Flow = serde_json::from_slice(&encoded)?;
    assert!(matches!(
        restored.invoke().await,
        Err(FlowInvokeError::InvalidFlow(
            FlowValidationError::Assertion(yosoi_assertions::AssertionError::Unbound)
        ))
    ));
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
fn contract_until_archive_requires_exact_successful_declared_check_report() -> Result<(), TestError>
{
    let plan = UntilModelContract::plan()?.clone();
    let document = ys::Document::html(
        CONTRACT_DOCUMENT_ID,
        CONTRACT_DOCUMENT_HTML.as_bytes().to_vec(),
    )?;
    let evaluated = AssertionGroup::<UntilModelContract>::new(plan.clone(), contract_checks())
        .evaluate(&document)?;
    assert!(evaluated.passed);
    assert_eq!(
        evaluated
            .checks
            .iter()
            .map(|check| (check.index, check.name.as_deref(), check.passed))
            .collect::<Vec<_>>(),
        [(0, Some("receipt"), Some(true)), (1, None, Some(true)),]
    );

    let mut missing = evaluated.clone();
    missing.checks.pop();
    assert!(contract_until_record(missing, "contract-missing-check").is_err());

    let mut extra = evaluated.clone();
    extra.checks.push(yosoi_assertions::CheckResult {
        index: 2,
        name: Some("undeclared".to_owned()),
        passed: Some(true),
        error: None,
    });
    assert!(contract_until_record(extra, "contract-extra-check").is_err());

    let mut wrong_index = evaluated.clone();
    wrong_index.checks[1].index = 9;
    assert!(contract_until_record(wrong_index, "contract-wrong-index").is_err());

    let mut wrong_name = evaluated.clone();
    wrong_name.checks[0].name = Some("other-check".to_owned());
    assert!(contract_until_record(wrong_name, "contract-wrong-name").is_err());

    let mut out_of_order = evaluated.clone();
    out_of_order.checks.swap(0, 1);
    for (position, check) in out_of_order.checks.iter_mut().enumerate() {
        check.index = position;
    }
    assert!(contract_until_record(out_of_order, "contract-out-of-order").is_err());

    let mut no_match = evaluated.clone();
    no_match.located = LocateOutcome::NoMatch {
        document_id: DocumentId::try_new(CONTRACT_DOCUMENT_ID)?,
    };
    assert!(contract_until_record(no_match, "contract-no-match").is_err());

    let mut indeterminate = evaluated.clone();
    indeterminate.located = LocateOutcome::Indeterminate {
        document_id: DocumentId::try_new(CONTRACT_DOCUMENT_ID)?,
        completeness: IncompleteEvidence::Unknown {
            reason_code: "forged-incomplete-evidence".to_owned(),
        },
        reason_code: "forged-incomplete-evidence".to_owned(),
    };
    assert!(contract_until_record(indeterminate, "contract-indeterminate").is_err());

    let mut field_issue = evaluated.clone();
    field_issue.field_issues.push(FieldIssue {
        field: FieldId::try_new("value")?,
        kind: FieldIssueKind::MissingRequired,
        evidence: Vec::new(),
    });
    assert!(contract_until_record(field_issue, "contract-field-issue").is_err());

    let mut extraction_diagnostic = evaluated;
    extraction_diagnostic
        .extraction_diagnostics
        .push(serde_json::json!({"kind": "changed-after-evaluation"}));
    assert!(
        contract_until_record(extraction_diagnostic, "contract-extraction-diagnostic").is_err()
    );

    let positive =
        AssertionGroup::<UntilModelContract>::new(plan, contract_checks()).evaluate(&document)?;
    assert!(contract_until_record(positive, "contract-valid").is_ok());

    let foreign_document = ys::Document::html(
        "foreign-contract-document",
        CONTRACT_DOCUMENT_HTML.as_bytes().to_vec(),
    )?;
    let foreign_report = AssertionGroup::<UntilModelContract>::new(
        UntilModelContract::plan()?.clone(),
        contract_checks(),
    )
    .evaluate(&foreign_document)?;
    assert!(foreign_report.passed);
    assert!(contract_until_record(foreign_report, "contract-foreign-document").is_err());

    let mut undeclared_output_id = serde_json::to_value(
        AssertionGroup::<UntilModelContract>::new(
            UntilModelContract::plan()?.clone(),
            contract_checks(),
        )
        .evaluate(&document)?,
    )?;
    let output_id = undeclared_output_id
        .pointer_mut("/located/result/findings/0/output_id")
        .ok_or("evaluated Contract report has no located finding output ID")?;
    *output_id = serde_json::json!("undeclared-output-id");
    let undeclared_output_id: AssertionReport = serde_json::from_value(undeclared_output_id)?;
    assert!(contract_until_record(undeclared_output_id, "contract-undeclared-output").is_err());

    let mut partial_finding = serde_json::to_value(
        AssertionGroup::<UntilModelContract>::new(
            UntilModelContract::plan()?.clone(),
            contract_checks(),
        )
        .evaluate(&document)?,
    )?;
    let completeness = partial_finding
        .pointer_mut("/located/result/findings/0/completeness")
        .ok_or("evaluated Contract report has no finding completeness")?;
    *completeness = serde_json::json!({
        "status": "partial",
        "reason_code": "synthetic-partial-evidence",
        "lost_items": 1
    });
    let partial_finding: AssertionReport = serde_json::from_value(partial_finding)?;
    assert!(partial_finding.passed);
    assert!(contract_until_record(partial_finding, "contract-partial-finding").is_err());
    Ok(())
}

const CONTRACT_DOCUMENT_ID: &str = "contract-observation";
const CONTRACT_DOCUMENT_HTML: &str = "<main id=record><p id=value>ready</p></main>";

fn contract_checks() -> [Check<'static, UntilModelContract>; 2] {
    [
        check(|contract: &UntilModelContract| contract.value == "ready").named("receipt"),
        check(|contract: &UntilModelContract| !contract.value.is_empty()),
    ]
}

fn contract_until_record(
    assertion: AssertionReport,
    receipt_id: &str,
) -> Result<AutomationRecord, TestError> {
    let report = UntilReport {
        version: 1,
        termination: UntilTermination::Satisfied,
        scope: UntilScope {
            session_id: "session-1".to_owned(),
            tab_id: "tab-1".to_owned(),
            document_epoch: 7,
            frame_id: Some("contract-frame-7".to_owned()),
            loader_id: Some("contract-loader-7".to_owned()),
        },
        trigger: None,
        evaluations: 1,
        checks: vec![UntilCheck {
            index: 0,
            source: "dom".to_owned(),
            state: UntilCheckState::Satisfied,
            evidence: Some(serde_json::json!({
                "report": serde_json::to_value(assertion)?,
                "observation_id": CONTRACT_DOCUMENT_ID,
                "document_epoch": 7,
                "observed_at_unix_ms": 1
            })),
            error: None,
        }],
        error: None,
    };
    let step =
        action::assert_all::<UntilModelContract>(UntilModelContract::plan()?, contract_checks())
            .until();
    record_with_step_and_observation(report, step, receipt_id, contract_observation())
}

fn contract_observation() -> Observation {
    Observation {
        browser: None,
        id: CONTRACT_DOCUMENT_ID.to_owned(),
        session_id: "session-1".to_owned(),
        tab_id: "tab-1".to_owned(),
        document_epoch: 7,
        html: Some(CONTRACT_DOCUMENT_HTML.to_owned()),
        url: Some("http://127.0.0.1/contract".to_owned()),
        screenshot: None,
    }
}

fn valid_report() -> UntilReport {
    UntilReport {
        version: 1,
        termination: UntilTermination::Satisfied,
        scope: UntilScope {
            session_id: "session-1".to_owned(),
            tab_id: "tab-1".to_owned(),
            document_epoch: 7,
            frame_id: Some("frame-raw-17".to_owned()),
            loader_id: Some("loader-raw-23".to_owned()),
        },
        trigger: Some(OperationReceipt {
            browser: None,
            id: "trigger-receipt".to_owned(),
            kind: "click".to_owned(),
            status: OperationStatus::Observed,
            result: Some(serde_json::json!({
                "value": null,
                "started_at_unix_us": 1_000
            })),
            observation: None,
            error: None,
        }),
        evaluations: 1,
        checks: vec![UntilCheck {
            index: 0,
            source: "dom".to_owned(),
            state: UntilCheckState::Satisfied,
            evidence: Some(serde_json::json!({
                "expected": {
                    "kind": "visible",
                    "selector": "#receipt"
                },
                "actual": true,
                "observation_id": "observation-1",
                "document_epoch": 7,
                "observed_at_unix_ms": 1
            })),
            error: None,
        }],
        error: None,
    }
}

fn record_with_report(
    report: UntilReport,
) -> Result<AutomationRecord, Box<dyn Error + Send + Sync>> {
    let step = action::click("#go").until(expect::visible("#receipt"));
    record_with_step(report, step, "until-receipt")
}

fn record_with_step(
    report: UntilReport,
    step: yosoi_flow::Step,
    receipt_id: &str,
) -> Result<AutomationRecord, Box<dyn Error + Send + Sync>> {
    record_with_step_and_observation(report, step, receipt_id, observation())
}

fn record_with_step_and_observation(
    report: UntilReport,
    step: yosoi_flow::Step,
    receipt_id: &str,
    observation: Observation,
) -> Result<AutomationRecord, Box<dyn Error + Send + Sync>> {
    let value = serde_json::to_value(report)?;
    let mut receipt = until_receipt(receipt_id, value);
    receipt.observation = Some(observation);
    let outcome = FlowOutcome {
        version: 3,
        flow: Flow::new([step]),
        steps: vec![StepOutcome {
            index: 0,
            flow_path: vec![0],
            receipt,
            failure: None,
            cancellation: None,
            cancelled_flow: None,
        }],
        terminal: FlowTermination::Completed,
        continuation_defaults: FlowPolicy::default(),
        stop_reason: None,
        skipped_steps: Vec::new(),
        cleanup: Vec::new(),
        failure_capture: None,
    };
    record_with_outcome(outcome, Vec::new())
}

fn record_with_outcome(
    outcome: FlowOutcome,
    operations: Vec<OperationReceipt>,
) -> Result<AutomationRecord, Box<dyn Error + Send + Sync>> {
    Ok(
        AutomationRecord::new("until-record", Vec::new(), operations)?
            .with_flow_outcome(outcome)?,
    )
}

fn until_receipt(id: &str, result: serde_json::Value) -> OperationReceipt {
    OperationReceipt {
        browser: None,
        id: id.to_owned(),
        kind: "until".to_owned(),
        status: OperationStatus::Observed,
        result: Some(result),
        observation: Some(observation()),
        error: None,
    }
}

fn accessibility_step(name: &str) -> Step {
    action::click("#go").until(expect::ax(name).role("button"))
}

fn accessibility_report(
    expected_name: &str,
    actual_name: &str,
    actual_role: &str,
    ignored: bool,
) -> UntilReport {
    UntilReport {
        version: 1,
        termination: UntilTermination::Satisfied,
        scope: UntilScope {
            session_id: "session-1".to_owned(),
            tab_id: "tab-1".to_owned(),
            document_epoch: 7,
            frame_id: Some("frame-raw-17".to_owned()),
            loader_id: Some("loader-raw-23".to_owned()),
        },
        trigger: Some(OperationReceipt {
            browser: None,
            id: "ax-trigger".to_owned(),
            kind: "click".to_owned(),
            status: OperationStatus::Observed,
            result: Some(serde_json::json!({
                "value": null,
                "started_at_unix_us": 1_000
            })),
            observation: None,
            error: None,
        }),
        evaluations: 1,
        checks: vec![UntilCheck {
            index: 0,
            source: "accessibility".to_owned(),
            state: UntilCheckState::Satisfied,
            evidence: Some(serde_json::json!({
                "name": expected_name,
                "role": "button",
                "nodes": [{
                    "ignored": ignored,
                    "name": {"value": actual_name},
                    "role": {"value": actual_role}
                }],
                "document_epoch": 7,
                "observed_at_unix_ms": 1
            })),
            error: None,
        }],
        error: None,
    }
}

fn network_url(attempt: &str) -> String {
    format!("http://127.0.0.1/api?attempt={attempt}")
}

fn network_step(attempt: &str) -> Step {
    action::click("#go").until(
        expect::response(network_url(attempt))
            .method("GET")
            .status(200)
            .json("/attempt", attempt),
    )
}

fn network_report(attempt: &str) -> UntilReport {
    UntilReport {
        version: 1,
        termination: UntilTermination::Satisfied,
        scope: UntilScope {
            session_id: "session-1".to_owned(),
            tab_id: "tab-1".to_owned(),
            document_epoch: 7,
            frame_id: Some("frame-raw-17".to_owned()),
            loader_id: Some("loader-raw-23".to_owned()),
        },
        trigger: Some(OperationReceipt {
            browser: None,
            id: format!("network-trigger-{attempt}"),
            kind: "click".to_owned(),
            status: OperationStatus::Observed,
            result: Some(serde_json::json!({
                "value": null,
                "started_at_unix_us": 1_000
            })),
            observation: None,
            error: None,
        }),
        evaluations: 1,
        checks: vec![UntilCheck {
            index: 0,
            source: "network".to_owned(),
            state: UntilCheckState::Satisfied,
            evidence: Some(serde_json::json!({
                "request_id": "request-raw-9",
                "url": network_url(attempt),
                "method": "GET",
                "status": 200,
                "top_level": true,
                "frame_id": "frame-raw-17",
                "loader_id": "loader-raw-23",
                "started_at_unix_us": 1_001,
                "document_epoch": 7,
                "observed_at_unix_ms": 1,
                "body": {"attempt": attempt}
            })),
            error: None,
        }],
        error: None,
    }
}

fn set_check_evidence_value(
    report: &mut UntilReport,
    key: &str,
    value: serde_json::Value,
) -> Result<(), TestError> {
    let evidence = report
        .checks
        .first_mut()
        .and_then(|check| check.evidence.as_mut())
        .and_then(serde_json::Value::as_object_mut)
        .ok_or_else(|| std_io::Error::other("network evidence missing"))?;
    evidence.insert(key.to_owned(), value);
    Ok(())
}

fn set_network_body_attempt(report: &mut UntilReport, attempt: &str) -> Result<(), TestError> {
    let body = report
        .checks
        .first_mut()
        .and_then(|check| check.evidence.as_mut())
        .and_then(|evidence| evidence.get_mut("body"))
        .and_then(serde_json::Value::as_object_mut)
        .ok_or_else(|| std_io::Error::other("network body evidence missing"))?;
    body.insert("attempt".to_owned(), serde_json::json!(attempt));
    Ok(())
}

fn set_network_padding(report: &mut UntilReport, padding: String) -> Result<(), TestError> {
    let body = report
        .checks
        .first_mut()
        .and_then(|check| check.evidence.as_mut())
        .and_then(|evidence| evidence.get_mut("body"))
        .and_then(serde_json::Value::as_object_mut)
        .ok_or_else(|| std_io::Error::other("network body evidence missing"))?;
    body.insert("padding".to_owned(), serde_json::Value::String(padding));
    Ok(())
}

fn observation() -> Observation {
    Observation {
        browser: None,
        id: "observation-1".to_owned(),
        session_id: "session-1".to_owned(),
        tab_id: "tab-1".to_owned(),
        document_epoch: 7,
        html: Some("<main><p id=receipt>ready</p></main>".to_owned()),
        url: Some("http://127.0.0.1/".to_owned()),
        screenshot: None,
    }
}

#[derive(ys::Contract)]
#[ys(
    id = "until-model-contract",
    description = "Contract used to test public Flow preflight",
    root = ys::locator::css("#record")
)]
struct UntilModelContract {
    #[ys(description = "Value", locator = ys::locator::css("#value").text())]
    value: String,
}
