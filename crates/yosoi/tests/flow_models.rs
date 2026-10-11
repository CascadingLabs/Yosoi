use yosoi::{
    action,
    automation_record::{OperationReceipt, OperationStatus},
    flow::{
        Condition, FailureCapturePolicy, Flow, FlowLimits, FlowOutcome, FlowTermination, Step,
        StepOutcome,
    },
};

#[test]
fn flow_steps_and_conditions_round_trip_as_typed_wire_values() {
    let flow = Flow::new([
        Step::Navigate {
            url: "https://example.com".to_owned(),
        },
        Step::Click {
            selector: "button[type=submit]".to_owned(),
        },
        Step::EnterText {
            selector: "#query".to_owned(),
            text: "weekly report".to_owned(),
        },
        Step::Wait { milliseconds: 25 },
        Step::Assert {
            condition: Condition::Exists {
                selector: ".result".to_owned(),
            },
        },
        Step::WaitUntil {
            condition: Condition::CountAtLeast {
                selector: ".result".to_owned(),
                count: 2,
            },
            timeout_ms: 500,
        },
        Step::Screenshot,
        Step::Evaluate {
            source: "document.title".to_owned(),
        },
    ]);

    let encoded = serde_json::to_string(&flow).expect("test fixture should serialize");
    let decoded: Flow = serde_json::from_str(&encoded).expect("flow should deserialize");

    assert_eq!(decoded, flow);
}

#[test]
fn action_helpers_construct_the_same_typed_steps() {
    assert_eq!(
        action::navigate("https://example.com"),
        Step::Navigate {
            url: "https://example.com".to_owned()
        }
    );
    assert_eq!(
        action::click("#go"),
        Step::Click {
            selector: "#go".to_owned()
        }
    );
    assert_eq!(
        action::enter_text("#query", "energy"),
        Step::EnterText {
            selector: "#query".to_owned(),
            text: "energy".to_owned(),
        }
    );
    assert_eq!(action::wait(12), Step::Wait { milliseconds: 12 });
    assert_eq!(action::screenshot(), Step::Screenshot);
    assert_eq!(
        Step::from(action::assert(Condition::Exists {
            selector: "#ready".to_owned(),
        })),
        Step::Assert {
            condition: Condition::Exists {
                selector: "#ready".to_owned(),
            },
        }
    );
    assert_eq!(
        action::wait_until(
            Condition::Visible {
                selector: "#ready".to_owned(),
            },
            1_000,
        ),
        Step::WaitUntil {
            condition: Condition::Visible {
                selector: "#ready".to_owned(),
            },
            timeout_ms: 1_000,
        }
    );
    assert_eq!(
        action::evaluate("40 + 2"),
        Step::Evaluate {
            source: "40 + 2".to_owned(),
        }
    );
}

#[test]
fn timeout_builders_are_milliseconds_and_legacy_microseconds_keep_their_unit() {
    let flow =
        Flow::new([action::screenshot().timeout(30_000)]).timeout(yosoi::timing::seconds(10));
    assert_eq!(yosoi::timing::seconds(60), 60_000);
    assert_eq!(yosoi::timing::milliseconds(5), 5);

    let encoded = serde_json::to_value(&flow).expect("Flow should serialize");
    assert_eq!(encoded["schema_version"], 3);
    assert_eq!(encoded["timeout"]["secs"], 10);
    assert_eq!(encoded["steps"][0]["timeout"]["secs"], 30);
    let decoded: Flow = serde_json::from_value(encoded).expect("Flow should deserialize");
    assert_eq!(decoded, flow);

    let legacy_flow: Flow = serde_json::from_str(r#"{"steps":[],"timeout_us":10000}"#)
        .expect("legacy Flow microseconds should deserialize");
    let migrated_flow = serde_json::to_value(&legacy_flow).expect("legacy Flow should serialize");
    assert_eq!(migrated_flow["schema_version"], 3);
    assert_eq!(migrated_flow["timeout"]["secs"], 0);
    assert_eq!(migrated_flow["timeout"]["nanos"], 10_000_000);
    assert_eq!(
        serde_json::from_value::<Flow>(migrated_flow).expect("migrated Flow should round trip"),
        legacy_flow
    );

    let legacy_step: Flow = serde_json::from_str(
        r#"{"steps":[{"kind":"timed","action":{"kind":"screenshot"},"timeout_us":10000}]}"#,
    )
    .expect("legacy action microseconds should deserialize");
    let migrated_step = serde_json::to_value(&legacy_step).expect("legacy action should serialize");
    assert_eq!(migrated_step["steps"][0]["timeout"]["secs"], 0);
    assert_eq!(migrated_step["steps"][0]["timeout"]["nanos"], 10_000_000);
    assert_eq!(
        serde_json::from_value::<Flow>(migrated_step).expect("migrated action should round trip"),
        legacy_step
    );
}

#[test]
fn nested_flows_are_native_steps_and_validation_bounds_expansion() {
    let child = Flow::new([action::screenshot()]).timeout(30_000);
    let parent = Flow::new([child.clone().into(), action::screenshot()]).timeout(10_000);
    parent.validate().expect("nested Flow should validate");

    let wire = serde_json::to_value(&parent).expect("nested Flow should serialize");
    assert_eq!(wire["steps"][0]["kind"], "nested_flow");
    let decoded: Flow = serde_json::from_value(wire).expect("nested Flow should deserialize");
    assert_eq!(decoded, parent);

    assert!(matches!(
        parent.validate_with_limits(FlowLimits {
            max_steps: 2,
            ..FlowLimits::default()
        }),
        Err(yosoi::flow::FlowValidationError::TooManySteps { .. })
    ));

    let too_deep = (0..10).fold(Flow::new([action::screenshot()]), |nested, _| {
        Flow::new([nested.into()])
    });
    assert!(matches!(
        too_deep.validate(),
        Err(yosoi::flow::FlowValidationError::TooDeep { .. })
    ));

    assert!(matches!(
        Flow::new([]).validate_with_limits(FlowLimits {
            max_serialized_bytes: 1,
            ..FlowLimits::default()
        }),
        Err(yosoi::flow::FlowValidationError::SerializedInputTooLarge { .. })
    ));

    let child_capture =
        Flow::new([action::screenshot()]).with_failure_capture(FailureCapturePolicy::Screenshot);
    assert!(matches!(
        Flow::new([child_capture.into()]).validate(),
        Err(yosoi::flow::FlowValidationError::NestedFailureCaptureUnsupported)
    ));
}

#[test]
fn flow_timeouts_reject_zero_overflow_and_ambiguous_persisted_units() {
    assert!(matches!(
        Flow::new([action::screenshot()]).timeout(0).validate(),
        Err(yosoi::flow::FlowValidationError::InvalidTimeout)
    ));
    let overflowing: Flow = serde_json::from_str(
        r#"{"schema_version":2,"steps":[],"timeout":{"secs":18446744073709551615,"nanos":999999999}}"#,
    )
    .expect("large serialized Duration should deserialize as an explicit duration");
    assert!(matches!(
        overflowing.validate(),
        Err(yosoi::flow::FlowValidationError::InvalidTimeout)
    ));
    assert!(
        serde_json::from_str::<Flow>(r#"{"schema_version":2,"steps":[],"timeout_us":10000}"#)
            .is_err()
    );
}

#[tokio::test(flavor = "current_thread")]
async fn invoke_validates_before_acquiring_browser_resources() {
    use yosoi::{flow::FlowInvokeError, policy::Policy, request::CancellationToken};

    let recipe = Flow::new([action::click(" ")]);
    let policy = Policy::default();
    let cancellation = CancellationToken::new();
    cancellation.cancel();

    for result in [
        recipe.invoke().await,
        recipe.with_cancellation(&cancellation).invoke().await,
        recipe.bind(&policy).invoke().await,
        recipe
            .bind(&policy)
            .with_cancellation(&cancellation)
            .invoke()
            .await,
    ] {
        assert!(matches!(result, Err(FlowInvokeError::InvalidFlow(_))));
        let error = result.expect_err("invalid recipe must fail before acquisition");
        assert!(error.partial_outcome().is_none());
        assert!(error.cleanup_error().is_none());
    }
}

#[test]
fn invoke_futures_support_send_without_consuming_recipe_or_lease() {
    use yosoi::{policy::Policy, request::CancellationToken, session::Work};

    fn check(recipe: &Flow, lease: &Work, policy: &Policy, token: &CancellationToken) {
        fn require_send(_: impl std::future::Future + Send) {}
        require_send(recipe.invoke());
        require_send(recipe.with_cancellation(token).invoke());
        require_send(recipe.with_lease(lease).invoke());
        require_send(recipe.with_lease(lease).with_cancellation(token).invoke());
        require_send(recipe.bind(policy).with_lease(lease).invoke());
        require_send(
            recipe
                .with_lease(lease)
                .bind(policy)
                .with_cancellation(token)
                .invoke(),
        );
        require_send(recipe.bind(policy).invoke());
        require_send(recipe.bind(policy).with_cancellation(token).invoke());
    }

    let _ = check;
}

#[test]
fn flow_validation_enforces_step_selector_and_wait_until_bounds() {
    let flow = Flow::new([
        Step::Click {
            selector: "#ok".to_owned(),
        },
        Step::WaitUntil {
            condition: Condition::Visible {
                selector: "#ready".to_owned(),
            },
            timeout_ms: 0,
        },
    ]);
    let limits = FlowLimits {
        max_steps: 1,
        max_depth: 8,
        max_selector_bytes: 8,
        max_source_bytes: 32,
        max_serialized_bytes: 1_048_576,
    };

    assert!(matches!(
        flow.validate_with_limits(limits),
        Err(yosoi::flow::FlowValidationError::TooManySteps { .. })
    ));

    let selector_too_long = Flow::new([Step::Click {
        selector: "#selector-too-long".to_owned(),
    }]);
    assert!(matches!(
        selector_too_long.validate_with_limits(FlowLimits {
            max_steps: 1,
            max_depth: 8,
            max_selector_bytes: 8,
            max_source_bytes: 32,
            max_serialized_bytes: 1_048_576,
        }),
        Err(yosoi::flow::FlowValidationError::SelectorTooLong { .. })
    ));

    let empty_selector = Flow::new([Step::Click {
        selector: " \t".to_owned(),
    }]);
    assert!(matches!(
        empty_selector.validate(),
        Err(yosoi::flow::FlowValidationError::EmptySelector { .. })
    ));

    let zero_timeout = Flow::new([Step::WaitUntil {
        condition: Condition::Exists {
            selector: "#ready".to_owned(),
        },
        timeout_ms: 0,
    }]);
    assert!(matches!(
        zero_timeout.validate(),
        Err(yosoi::flow::FlowValidationError::ZeroTimeout { .. })
    ));
}

#[test]
fn failed_outcome_serialization_keeps_earlier_and_terminal_step_receipts() {
    let flow = Flow::new([
        Step::Click {
            selector: "#continue".to_owned(),
        },
        Step::Assert {
            condition: Condition::Exists {
                selector: "#missing".to_owned(),
            },
        },
        Step::Screenshot,
    ]);
    let outcome = FlowOutcome {
        version: 1,
        flow,
        steps: vec![
            StepOutcome {
                index: 0,
                flow_path: Vec::new(),
                receipt: receipt("observed", OperationStatus::Observed, None),
                failure: None,
                cancellation: None,
                cancelled_flow: None,
            },
            StepOutcome {
                index: 1,
                flow_path: Vec::new(),
                receipt: receipt(
                    "assertion",
                    OperationStatus::Rejected,
                    Some("selector matched no nodes"),
                ),
                failure: None,
                cancellation: None,
                cancelled_flow: None,
            },
        ],
        terminal: FlowTermination::Failed,
        continuation_defaults: yosoi::flow::FlowPolicy::default(),
        stop_reason: None,
        skipped_steps: Vec::new(),
        cleanup: Vec::new(),
        failure_capture: None,
    };

    let encoded = serde_json::to_string(&outcome).expect("outcome should serialize");
    let value: serde_json::Value =
        serde_json::from_str(&encoded).expect("serialized outcome should be valid JSON");
    let step_records = value["steps"]
        .as_array()
        .expect("outcome should retain its step array");

    assert_eq!(step_records.len(), 2);
    assert_eq!(step_records[0]["receipt"]["status"], "observed");
    assert_eq!(step_records[1]["receipt"]["status"], "rejected");
    assert_eq!(value["terminal"], "failed");
}

#[test]
fn flow_capture_policy_and_legacy_flow_outcomes_round_trip() {
    let legacy_flow: Flow = serde_json::from_str(r#"{"steps":[]}"#)
        .expect("legacy flow without a capture policy should deserialize");
    assert_eq!(
        legacy_flow.failure_capture_policy(),
        FailureCapturePolicy::Disabled
    );
    let legacy_flow_wire =
        serde_json::to_value(&legacy_flow).expect("default flow should serialize");
    assert!(legacy_flow_wire.get("capture_on_failure").is_none());
    let legacy_flow_round_trip: Flow =
        serde_json::from_value(legacy_flow_wire).expect("default flow should round trip");
    assert_eq!(legacy_flow_round_trip, legacy_flow);

    let legacy_outcome: FlowOutcome =
        serde_json::from_str(r#"{"version":1,"flow":{"steps":[]},"steps":[],"terminal":"failed"}"#)
            .expect("legacy flow outcome without a capture receipt should deserialize");
    assert!(legacy_outcome.failure_capture.is_none());
    let legacy_outcome_wire =
        serde_json::to_value(&legacy_outcome).expect("legacy flow outcome should serialize");
    assert!(legacy_outcome_wire.get("failure_capture").is_none());
    let legacy_outcome_round_trip: FlowOutcome =
        serde_json::from_value(legacy_outcome_wire).expect("legacy flow outcome should round trip");
    assert_eq!(legacy_outcome_round_trip.version, legacy_outcome.version);
    assert_eq!(legacy_outcome_round_trip.flow, legacy_outcome.flow);
    assert_eq!(
        legacy_outcome_round_trip.steps.len(),
        legacy_outcome.steps.len()
    );
    assert_eq!(legacy_outcome_round_trip.terminal, FlowTermination::Failed);
    assert!(legacy_outcome_round_trip.failure_capture.is_none());

    let flow = Flow::new([Step::Click {
        selector: "#submit".to_owned(),
    }])
    .with_failure_capture(FailureCapturePolicy::Screenshot);
    let flow_wire = serde_json::to_value(&flow).expect("capture policy should serialize");
    assert_eq!(flow_wire["capture_on_failure"], "screenshot");
    let flow_round_trip: Flow =
        serde_json::from_value(flow_wire).expect("screenshot capture policy should deserialize");
    assert_eq!(flow_round_trip, flow);

    // A failed primary step remains failed even if the follow-up screenshot
    // receipt is unknown.
    let outcome = FlowOutcome {
        version: 1,
        flow,
        steps: vec![StepOutcome {
            index: 0,
            flow_path: Vec::new(),
            receipt: receipt("primary", OperationStatus::Rejected, Some("click rejected")),
            failure: None,
            cancellation: None,
            cancelled_flow: None,
        }],
        terminal: FlowTermination::Failed,
        continuation_defaults: yosoi::flow::FlowPolicy::default(),
        stop_reason: None,
        skipped_steps: Vec::new(),
        cleanup: Vec::new(),
        failure_capture: Some(receipt(
            "failure-capture",
            OperationStatus::Unknown,
            Some("screenshot outcome unknown"),
        )),
    };
    let outcome_wire =
        serde_json::to_value(&outcome).expect("failure capture outcome should serialize");
    let outcome_round_trip: FlowOutcome =
        serde_json::from_value(outcome_wire).expect("failure capture outcome should deserialize");
    assert_eq!(outcome_round_trip.terminal, FlowTermination::Failed);
    assert_eq!(
        outcome_round_trip
            .failure_capture
            .as_ref()
            .map(|receipt| receipt.status),
        Some(OperationStatus::Unknown)
    );
}

fn receipt(id: &str, status: OperationStatus, error: Option<&str>) -> OperationReceipt {
    OperationReceipt {
        id: id.to_owned(),
        kind: "test".to_owned(),
        status,
        result: None,
        observation: None,
        error: error.map(str::to_owned),
    }
}
