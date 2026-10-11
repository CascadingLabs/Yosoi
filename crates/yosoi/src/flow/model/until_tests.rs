use super::{Condition, Step};
use crate::{
    expect::{self, Expectation, UntilExpectation},
    flow::{Continuation, StopScope},
    request::CancellationToken,
};
use std::time::Duration;

#[test]
fn trigger_settings_are_lifted_to_the_compound_step() {
    let failure = Continuation::Stop(StopScope::Invocation);
    let step = Step::Click {
        selector: "button.checkout".into(),
    }
    .timeout(300)
    .on_failure(failure)
    .until(expect::visible("[data-state=complete]"));

    assert_eq!(step.timeout_duration(), Some(Duration::from_millis(300)));
    assert_eq!(step.failure_override(), Some(failure));
    let Step::Until {
        trigger: Some(trigger),
        expectation: Expectation::Condition { .. },
    } = step.operation()
    else {
        panic!("expected an Until action with its condition");
    };
    assert!(matches!(trigger.as_ref(), Step::Click { .. }));
}

#[test]
fn attached_contract_settings_override_trigger_settings() {
    let inherited_failure = Continuation::Stop(StopScope::Invocation);
    let attached_failure = Continuation::Continue;
    let trigger = Step::Click {
        selector: "button.checkout".into(),
    }
    .timeout(300)
    .on_failure(inherited_failure);
    let mut attached = UntilExpectation::new(expect::visible("#confirmation"));
    attached.timeout = Some(Duration::from_millis(700));
    attached.on_failure = Some(attached_failure);

    let step = trigger.until(attached);

    assert_eq!(step.timeout_duration(), Some(Duration::from_millis(700)));
    assert_eq!(step.failure_override(), Some(attached_failure));
}

#[test]
fn lifted_cancellation_binding_is_required_after_serialization() {
    let token = CancellationToken::new();
    let step = Step::Click {
        selector: "button.checkout".into(),
    }
    .with_cancellation(&token)
    .until(Condition::Visible {
        selector: "#confirmation".into(),
    });
    assert!(!step.requires_cancellation_binding());

    let encoded = serde_json::to_vec(&step).expect("step should serialize");
    let restored: Step = serde_json::from_slice(&encoded).expect("step should deserialize");

    assert!(restored.requires_cancellation_binding());
}
