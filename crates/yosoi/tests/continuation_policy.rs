use serde_json::json;
use yosoi::{
    flow::{Continuation, Flow, Step, StopScope},
    policy::{FlowPolicy, Policy},
};

#[test]
fn continuation_options_are_typed_explicit_and_identity_sensitive() {
    let defaults = FlowPolicy::default();
    assert_eq!(defaults.on_failure, Continuation::Continue);
    assert_eq!(defaults.on_cancellation, Continuation::Continue);
    assert_eq!(Policy::default().flow, defaults);

    let mut policy = Policy::default();
    policy.flow.on_failure = Continuation::Stop(StopScope::CurrentFlow);
    policy.flow.on_cancellation = Continuation::Stop(StopScope::Invocation);
    let encoded_policy = serde_json::to_value(&policy).expect("policy should serialize");
    assert_eq!(
        encoded_policy["flow"],
        json!({
            "on_failure": {"kind": "stop", "scope": "current_flow"},
            "on_cancellation": {"kind": "stop", "scope": "invocation"}
        })
    );
    assert_ne!(
        Policy::default()
            .effective_identity()
            .expect("default identity"),
        policy.effective_identity().expect("configured identity")
    );

    // Explicit Continue remains a real local override when an ancestor stops.
    let flow = Flow::new([Step::Screenshot.on_failure(Continuation::Continue)])
        .on_failure(Continuation::Stop(StopScope::Invocation))
        .on_cancellation(Continuation::Stop(StopScope::CurrentFlow));
    let encoded_flow = serde_json::to_value(&flow).expect("Flow should serialize");
    assert_eq!(
        encoded_flow["on_failure"],
        json!({"kind": "stop", "scope": "invocation"})
    );
    assert_eq!(
        encoded_flow["on_cancellation"],
        json!({"kind": "stop", "scope": "current_flow"})
    );
    assert_eq!(
        encoded_flow["steps"][0]["on_failure"],
        json!({"kind": "continue"})
    );
    let reopened: Flow =
        serde_json::from_value(encoded_flow).expect("Flow overrides should reopen");
    assert_eq!(
        serde_json::to_value(reopened).expect("reopened Flow"),
        serde_json::to_value(flow).expect("original Flow")
    );
}

#[test]
fn legacy_policy_without_flow_settings_uses_continue_defaults() {
    let mut encoded = serde_json::to_value(Policy::default()).expect("Policy should serialize");
    encoded
        .as_object_mut()
        .expect("Policy serialization should be an object")
        .remove("flow");

    let reopened: Policy =
        serde_json::from_value(encoded).expect("legacy Policy should preserve its behavior");
    assert_eq!(reopened.flow, FlowPolicy::default());
}
