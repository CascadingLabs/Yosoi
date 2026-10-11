use crate::{
    assertions::LocalAssertion,
    expect::{Expectation, UntilExpectation},
    flow::{Condition, Continuation, Step},
    request::CancellationToken,
};
use std::time as std_time;

#[derive(Clone, Debug)]
enum AssertionKind {
    Condition(Condition),
    Contract(LocalAssertion),
}

/// A typed assertion that can run once or wait through `until`.
#[derive(Clone, Debug)]
pub struct AssertionBuilder {
    assertion: AssertionKind,
    timeout_ms: Option<u64>,
    on_failure: Option<Continuation>,
    on_cancellation: Option<Continuation>,
    cancellation: Option<CancellationToken>,
}

impl AssertionBuilder {
    pub(crate) const fn new_contract(assertion: LocalAssertion) -> Self {
        Self {
            assertion: AssertionKind::Contract(assertion),
            timeout_ms: None,
            on_failure: None,
            on_cancellation: None,
            cancellation: None,
        }
    }

    pub(crate) const fn new_condition(condition: Condition) -> Self {
        Self {
            assertion: AssertionKind::Condition(condition),
            timeout_ms: None,
            on_failure: None,
            on_cancellation: None,
            cancellation: None,
        }
    }

    /// Sets the timeout in milliseconds; it applies to the complete assertion step.
    pub const fn timeout(mut self, milliseconds: u64) -> Self {
        self.timeout_ms = Some(milliseconds);
        self
    }

    /// Sets this assertion step's failure continuation.
    pub const fn on_failure(mut self, continuation: Continuation) -> Self {
        self.on_failure = Some(continuation);
        self
    }

    /// Sets this assertion step's cancellation continuation.
    pub const fn on_cancellation(mut self, continuation: Continuation) -> Self {
        self.on_cancellation = Some(continuation);
        self
    }

    /// Binds a local cancellation token to this assertion step.
    pub fn with_cancellation(mut self, token: &CancellationToken) -> Self {
        self.cancellation = Some(token.clone());
        self
    }

    /// Waits for this assertion without a separate trigger action.
    pub fn until(self) -> Step {
        Step::until_without_trigger(self)
    }

    fn into_step(self) -> Step {
        let Self {
            assertion,
            timeout_ms,
            on_failure,
            on_cancellation,
            cancellation,
        } = self;
        let mut step = match assertion {
            AssertionKind::Condition(condition) => Step::Assert { condition },
            AssertionKind::Contract(assertion) => Step::AssertAll { assertion },
        };
        if let Some(timeout_ms) = timeout_ms {
            step = step.timeout(timeout_ms);
        }
        if let Some(continuation) = on_failure {
            step = step.on_failure(continuation);
        }
        if let Some(continuation) = on_cancellation {
            step = step.on_cancellation(continuation);
        }
        if let Some(token) = cancellation.as_ref() {
            step = step.with_cancellation(token);
        }
        step
    }
}

impl From<AssertionBuilder> for Step {
    fn from(builder: AssertionBuilder) -> Self {
        builder.into_step()
    }
}

impl From<AssertionBuilder> for UntilExpectation {
    fn from(builder: AssertionBuilder) -> Self {
        let AssertionBuilder {
            assertion,
            timeout_ms,
            on_failure,
            on_cancellation,
            cancellation,
        } = builder;
        let expectation = match assertion {
            AssertionKind::Condition(condition) => Expectation::Condition { condition },
            AssertionKind::Contract(assertion) => Expectation::Contract { assertion },
        };
        let mut expected = Self::new(expectation);
        expected.timeout = timeout_ms.map(std_time::Duration::from_millis);
        expected.on_failure = on_failure;
        expected.on_cancellation = on_cancellation;
        expected.cancellation = cancellation;
        expected
    }
}

#[cfg(test)]
mod tests {
    use crate::expect;
    use crate::{
        action,
        flow::{Condition, Continuation, Step, StopScope},
    };
    use std::time as std_time;

    #[test]
    fn condition_assertion_converts_to_an_immediate_assert_step() {
        let condition = Condition::Visible {
            selector: "#ready".into(),
        };
        let step: Step = action::assert(condition.clone()).into();

        assert_eq!(step, Step::Assert { condition });
        let encoded = serde_json::to_value(step).expect("step should serialize");
        assert_eq!(encoded["kind"], "assert");
    }

    #[test]
    fn condition_assertion_can_wait_without_a_trigger() {
        let condition = Condition::Visible {
            selector: "#ready".into(),
        };
        let step = action::assert(condition.clone()).until();

        assert!(matches!(
            step.operation(),
            Step::Until {
                trigger: None,
                expectation: expect::Expectation::Condition {
                    condition: expected
                }
            } if expected == &condition
        ));
        let encoded = serde_json::to_value(step).expect("Until step should serialize");
        assert_eq!(encoded["kind"], "until");
        assert_eq!(encoded["expectation"]["kind"], "condition");
    }

    #[test]
    fn click_until_assertion_keeps_nearest_modifiers_in_order() {
        let inherited_failure = Continuation::Stop(StopScope::Invocation);
        let attached_failure = Continuation::Continue;
        let attached_cancellation = Continuation::Stop(StopScope::CurrentFlow);
        let condition = Condition::Exists {
            selector: "#confirmation".into(),
        };
        let builder = action::assert(condition.clone())
            .timeout(700)
            .on_failure(attached_failure)
            .on_cancellation(attached_cancellation);
        let trigger = action::click("#place-order")
            .timeout(300)
            .on_failure(inherited_failure);
        let combined = trigger.until(builder);

        assert_eq!(
            combined.timeout_duration(),
            Some(std_time::Duration::from_millis(700))
        );
        assert_eq!(combined.failure_override(), Some(attached_failure));
        assert_eq!(
            combined.cancellation_override(),
            Some(attached_cancellation)
        );

        let encoded = serde_json::to_value(
            action::click("#place-order").until(action::assert(condition.clone())),
        )
        .expect("triggered Until should serialize");
        assert_eq!(encoded["kind"], "until");
        assert_eq!(encoded["trigger"]["kind"], "click");
        assert_eq!(encoded["expectation"]["kind"], "condition");

        let step = combined.timeout(900).on_failure(inherited_failure);

        assert_eq!(
            step.timeout_duration(),
            Some(std_time::Duration::from_millis(900))
        );
        assert_eq!(step.failure_override(), Some(inherited_failure));
        assert_eq!(step.cancellation_override(), Some(attached_cancellation));
        assert!(matches!(
            step.operation(),
            Step::Until {
                trigger: Some(trigger),
                expectation: expect::Expectation::Condition {
                    condition: expected
                }
            } if matches!(trigger.as_ref(), Step::Click { selector } if selector == "#place-order")
                && expected == &condition
        ));
    }
}
