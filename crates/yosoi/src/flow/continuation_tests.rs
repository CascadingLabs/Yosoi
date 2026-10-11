use super::{ActionExecutionFuture, execute_flow_steps_with_policy};
use crate::{
    automation_record::{OperationReceipt, OperationStatus},
    flow::{
        Continuation, Flow, FlowCancellationCause, FlowFailureCause, FlowPolicy, FlowStopCause,
        FlowTermination, Step, StopScope,
    },
    request::CancellationToken,
    session::SessionError,
};
use std::{
    sync::{Arc, Mutex},
    time::Duration,
};

#[derive(Clone, Copy, Debug)]
enum Event {
    Failure,
    Cancellation,
}

impl Event {
    const fn cause(self) -> FlowStopCause {
        match self {
            Self::Failure => FlowStopCause::Failure,
            Self::Cancellation => FlowStopCause::Cancellation,
        }
    }
}

fn failure_options() -> [Option<Continuation>; 4] {
    [
        None,
        Some(Continuation::Continue),
        Some(Continuation::Stop(StopScope::CurrentFlow)),
        Some(Continuation::Stop(StopScope::Invocation)),
    ]
}

fn policy_for(event: Event, continuation: Continuation) -> FlowPolicy {
    let mut policy = FlowPolicy::default();
    match event {
        Event::Failure => policy.on_failure = continuation,
        Event::Cancellation => policy.on_cancellation = continuation,
    }
    policy
}

fn configure_flow(flow: Flow, event: Event, continuation: Option<Continuation>) -> Flow {
    match (event, continuation) {
        (Event::Failure, Some(value)) => flow.on_failure(value),
        (Event::Cancellation, Some(value)) => flow.on_cancellation(value),
        (_, None) => flow,
    }
}

fn configure_step(step: Step, event: Event, continuation: Option<Continuation>) -> Step {
    match (event, continuation) {
        (Event::Failure, Some(value)) => step.on_failure(value),
        (Event::Cancellation, Some(value)) => step.on_cancellation(value),
        (_, None) => step,
    }
}

fn click(label: &str) -> Step {
    Step::Click {
        selector: label.to_owned(),
    }
}

fn receipt(label: &str, status: OperationStatus) -> OperationReceipt {
    OperationReceipt {
        id: format!("mock-{label}"),
        kind: "click".to_owned(),
        status,
        result: None,
        observation: None,
        error: (status == OperationStatus::Rejected).then(|| "mock rejection".to_owned()),
    }
}

fn trace_snapshot(trace: &Arc<Mutex<Vec<String>>>) -> Vec<String> {
    trace
        .lock()
        .expect("mock trace mutex should not be poisoned")
        .clone()
}

async fn run_matrix_case(
    event: Event,
    policy_continuation: Continuation,
    parent_override: Option<Continuation>,
    child_override: Option<Continuation>,
    leaf_override: Option<Continuation>,
) {
    let step_token = CancellationToken::new();
    if matches!(event, Event::Cancellation) {
        step_token.cancel();
    }
    let leaf = configure_step(
        click("leaf").with_cancellation(&step_token),
        event,
        leaf_override,
    );
    let child = configure_flow(
        Flow::new([leaf, click("child_sibling")]),
        event,
        child_override,
    );
    let root = configure_flow(
        Flow::new([child.into(), click("parent_sibling")]),
        event,
        parent_override,
    );
    let policy = policy_for(event, policy_continuation);
    let root_token = CancellationToken::new();
    let trace = Arc::new(Mutex::new(Vec::new()));
    let execute_trace = Arc::clone(&trace);
    let execute = move |step: Step,
                        _timeout: Duration,
                        _action_token: CancellationToken|
          -> ActionExecutionFuture<'static> {
        let trace = Arc::clone(&execute_trace);
        let mut label = String::new();
        if let Step::Click { selector } = &step {
            label.clone_from(selector);
        }
        Box::pin(async move {
            trace
                .lock()
                .expect("mock trace mutex should not be poisoned")
                .push(label.clone());
            if label == "leaf" {
                match event {
                    Event::Failure => Ok(receipt(&label, OperationStatus::Rejected)),
                    Event::Cancellation => Err(SessionError::InvalidInput),
                }
            } else {
                Ok(receipt(&label, OperationStatus::Observed))
            }
        })
    };

    let result = execute_flow_steps_with_policy(
        &root,
        Duration::from_secs(1),
        policy,
        &root_token,
        || false,
        execute,
    )
    .await;

    let selected = leaf_override
        .or(child_override)
        .or(parent_override)
        .unwrap_or(policy_continuation);
    let (dispatched_trace, expected_skipped, expected_scope) = match selected {
        Continuation::Continue => (
            vec!["leaf", "child_sibling", "parent_sibling"],
            Vec::new(),
            None,
        ),
        Continuation::Stop(StopScope::CurrentFlow) => (
            vec!["leaf", "parent_sibling"],
            vec![vec![0, 1]],
            Some(StopScope::CurrentFlow),
        ),
        Continuation::Stop(StopScope::Invocation) => (
            vec!["leaf"],
            vec![vec![0, 1], vec![1]],
            Some(StopScope::Invocation),
        ),
    };
    let expected_trace = if matches!(event, Event::Cancellation) {
        dispatched_trace
            .into_iter()
            .filter(|label| *label != "leaf")
            .collect::<Vec<_>>()
    } else {
        dispatched_trace
    };
    assert_eq!(
        trace_snapshot(&trace),
        expected_trace
            .iter()
            .map(|label| (*label).to_owned())
            .collect::<Vec<_>>()
    );
    assert_eq!(
        result
            .steps
            .iter()
            .map(|step| step.flow_path.clone())
            .collect::<Vec<_>>(),
        match selected {
            Continuation::Continue => vec![vec![0, 0], vec![0, 1], vec![1]],
            Continuation::Stop(StopScope::CurrentFlow) => vec![vec![0, 0], vec![1]],
            Continuation::Stop(StopScope::Invocation) => vec![vec![0, 0]],
        },
    );
    assert_eq!(
        result
            .skipped_steps
            .iter()
            .map(|step| step.flow_path.clone())
            .collect::<Vec<_>>(),
        expected_skipped
    );
    let expected_terminal = match selected {
        Continuation::Continue | Continuation::Stop(StopScope::CurrentFlow) => {
            FlowTermination::CompletedWithIssues
        }
        Continuation::Stop(StopScope::Invocation) => match event {
            Event::Failure => FlowTermination::Failed,
            Event::Cancellation => FlowTermination::Cancelled,
        },
    };
    assert_eq!(result.terminal, expected_terminal);

    let first = result.steps.first().expect("the failing leaf is attempted");
    match event {
        Event::Failure => {
            assert_eq!(first.failure, Some(FlowFailureCause::Rejected));
            assert_eq!(first.cancellation, None);
            assert_eq!(first.receipt.status, OperationStatus::Rejected);
        }
        Event::Cancellation => {
            assert_eq!(first.failure, None);
            assert_eq!(first.cancellation, Some(FlowCancellationCause::Step));
            assert_eq!(first.receipt.status, OperationStatus::Rejected);
        }
    }
    for skipped in &result.skipped_steps {
        assert_eq!(skipped.stopped_by, [0, 0]);
        assert_eq!(skipped.cause, event.cause());
        assert_eq!(skipped.scope, expected_scope.expect("a stop has a scope"));
    }
    match expected_scope {
        Some(StopScope::Invocation) => {
            let stop_reason = result.stop_reason.expect("Stop policy retains its reason");
            assert_eq!(stop_reason.flow_path, [0, 0]);
            assert_eq!(stop_reason.cause, event.cause());
            assert_eq!(stop_reason.continuation, Some(selected));
        }
        Some(StopScope::CurrentFlow) | None => assert!(result.stop_reason.is_none()),
    }
}

#[tokio::test]
async fn nearest_continuation_override_controls_real_nested_scheduling_for_both_events() {
    let policies = [
        Continuation::Continue,
        Continuation::Stop(StopScope::CurrentFlow),
        Continuation::Stop(StopScope::Invocation),
    ];
    let overrides = failure_options();
    for event in [Event::Failure, Event::Cancellation] {
        let mut cases = 0;
        for policy_continuation in policies {
            for parent_override in overrides {
                for child_override in overrides {
                    for leaf_override in overrides {
                        run_matrix_case(
                            event,
                            policy_continuation,
                            parent_override,
                            child_override,
                            leaf_override,
                        )
                        .await;
                        cases += 1;
                    }
                }
            }
        }
        assert_eq!(
            cases, 192,
            "matrix should cover every policy/scope combination"
        );
    }
}

#[tokio::test]
async fn current_flow_stop_restores_two_ancestor_siblings_and_is_invocation_local() {
    let root = Flow::new([
        Flow::new([
            Flow::new([click("leaf"), click("inner_sibling")]).into(),
            click("middle_sibling"),
        ])
        .into(),
        click("root_sibling"),
    ]);
    let policy = policy_for(Event::Failure, Continuation::Stop(StopScope::CurrentFlow));
    let root_token = CancellationToken::new();

    for _ in 0..2 {
        let trace = Arc::new(Mutex::new(Vec::new()));
        let execute_trace = Arc::clone(&trace);
        let execute = move |step: Step,
                            _timeout: Duration,
                            _token: CancellationToken|
              -> ActionExecutionFuture<'static> {
            let trace = Arc::clone(&execute_trace);
            let mut label = String::new();
            if let Step::Click { selector } = &step {
                label.clone_from(selector);
            }
            Box::pin(async move {
                trace
                    .lock()
                    .expect("mock trace mutex should not be poisoned")
                    .push(label.clone());
                let status = if label == "leaf" {
                    OperationStatus::Rejected
                } else {
                    OperationStatus::Observed
                };
                Ok(receipt(&label, status))
            })
        };
        let result = execute_flow_steps_with_policy(
            &root,
            Duration::from_secs(1),
            policy,
            &root_token,
            || false,
            execute,
        )
        .await;
        assert_eq!(
            trace_snapshot(&trace),
            vec![
                "leaf".to_owned(),
                "middle_sibling".to_owned(),
                "root_sibling".to_owned()
            ]
        );
        assert_eq!(result.steps[0].flow_path, [0, 0, 0]);
        assert!(!root_token.is_cancelled());
        assert_eq!(
            result
                .skipped_steps
                .iter()
                .map(|step| step.flow_path.clone())
                .collect::<Vec<_>>(),
            vec![vec![0, 0, 1]]
        );
        assert!(result.stop_reason.is_none());
    }
}

#[tokio::test]
async fn stop_invocation_does_not_cancel_a_shared_application_token() {
    let root_token = CancellationToken::new();
    let flow = Flow::new([click("critical"), click("skipped")])
        .on_failure(Continuation::Stop(StopScope::Invocation));
    let policy = FlowPolicy::default();
    let trace = Arc::new(Mutex::new(Vec::new()));
    let execute_trace = Arc::clone(&trace);
    let first = execute_flow_steps_with_policy(
        &flow,
        Duration::from_secs(1),
        policy,
        &root_token,
        || false,
        move |step, _timeout, _token| -> ActionExecutionFuture<'static> {
            let trace = Arc::clone(&execute_trace);
            let mut label = String::new();
            if let Step::Click { selector } = &step {
                label.clone_from(selector);
            }
            Box::pin(async move {
                trace
                    .lock()
                    .expect("mock trace mutex should not be poisoned")
                    .push(label.clone());
                let status = if label == "critical" {
                    OperationStatus::Rejected
                } else {
                    OperationStatus::Observed
                };
                Ok(receipt(&label, status))
            })
        },
    )
    .await;
    assert_eq!(first.terminal, FlowTermination::Failed);
    assert_eq!(trace_snapshot(&trace), vec!["critical".to_owned()]);
    assert!(!root_token.is_cancelled());

    let unrelated = Flow::new([click("unrelated")]);
    let second_trace = Arc::new(Mutex::new(Vec::new()));
    let execute_trace = Arc::clone(&second_trace);
    let second = execute_flow_steps_with_policy(
        &unrelated,
        Duration::from_secs(1),
        policy,
        &root_token,
        || false,
        move |step, _timeout, _token| -> ActionExecutionFuture<'static> {
            let trace = Arc::clone(&execute_trace);
            let mut label = String::new();
            if let Step::Click { selector } = &step {
                label.clone_from(selector);
            }
            Box::pin(async move {
                trace
                    .lock()
                    .expect("mock trace mutex should not be poisoned")
                    .push(label.clone());
                Ok(receipt(&label, OperationStatus::Observed))
            })
        },
    )
    .await;
    assert_eq!(second.terminal, FlowTermination::Completed);
    assert_eq!(trace_snapshot(&second_trace), vec!["unrelated".to_owned()]);
    assert!(!root_token.is_cancelled());
}

#[tokio::test]
async fn current_flow_stop_at_root_records_an_invocation_stop_reason() {
    let flow = Flow::new([click("critical"), click("skipped")]);
    let policy = policy_for(Event::Failure, Continuation::Stop(StopScope::CurrentFlow));
    let root_token = CancellationToken::new();
    let result = execute_flow_steps_with_policy(
        &flow,
        Duration::from_secs(1),
        policy,
        &root_token,
        || false,
        move |step, _timeout, _token| -> ActionExecutionFuture<'static> {
            let mut label = String::new();
            if let Step::Click { selector } = &step {
                label.clone_from(selector);
            }
            Box::pin(async move {
                let status = if label == "critical" {
                    OperationStatus::Rejected
                } else {
                    OperationStatus::Observed
                };
                Ok(receipt(&label, status))
            })
        },
    )
    .await;

    assert_eq!(result.terminal, FlowTermination::Failed);
    assert_eq!(result.skipped_steps.len(), 1);
    assert_eq!(result.skipped_steps[0].flow_path, [1]);
    assert_eq!(result.skipped_steps[0].scope, StopScope::CurrentFlow);
    let stop_reason = result
        .stop_reason
        .expect("root stop has an invocation reason");
    assert_eq!(stop_reason.flow_path, [0]);
    assert_eq!(stop_reason.cause, FlowStopCause::Failure);
    assert_eq!(
        stop_reason.continuation,
        Some(Continuation::Stop(StopScope::CurrentFlow))
    );
    assert!(!root_token.is_cancelled());
}

#[tokio::test]
async fn invocation_and_session_cancellation_cannot_be_revived_by_continue() {
    let root = Flow::new([
        configure_flow(
            Flow::new([
                configure_step(
                    click("leaf"),
                    Event::Cancellation,
                    Some(Continuation::Continue),
                ),
                click("child_sibling"),
            ])
            .on_cancellation(Continuation::Continue),
            Event::Failure,
            None,
        )
        .into(),
        click("parent_sibling").on_cancellation(Continuation::Continue),
    ])
    .on_cancellation(Continuation::Continue);
    let policy = policy_for(Event::Cancellation, Continuation::Continue);
    let root_token = CancellationToken::new();
    root_token.cancel();
    let trace = Arc::new(Mutex::new(Vec::new()));
    let execute_trace = Arc::clone(&trace);
    let execute = move |step: Step,
                        _timeout: Duration,
                        action_token: CancellationToken|
          -> ActionExecutionFuture<'static> {
        let trace = Arc::clone(&execute_trace);
        let mut label = String::new();
        if let Step::Click { selector } = &step {
            label.clone_from(selector);
        }
        Box::pin(async move {
            if action_token.is_cancelled() {
                return Err(SessionError::Cancelled);
            }
            trace
                .lock()
                .expect("mock trace mutex should not be poisoned")
                .push(label.clone());
            Ok(receipt(&label, OperationStatus::Observed))
        })
    };
    let result = execute_flow_steps_with_policy(
        &root,
        Duration::from_secs(1),
        policy,
        &root_token,
        || false,
        execute,
    )
    .await;
    assert!(trace_snapshot(&trace).is_empty());
    assert_ne!(result.terminal, FlowTermination::Completed);
    assert_eq!(
        result.steps.first().and_then(|step| step.cancellation),
        Some(FlowCancellationCause::Invocation)
    );
    assert_eq!(
        result.stop_reason.as_ref().map(|reason| reason.cause),
        Some(FlowStopCause::Cancellation)
    );
    assert_eq!(
        result
            .skipped_steps
            .iter()
            .map(|step| step.flow_path.clone())
            .collect::<Vec<_>>(),
        vec![vec![0, 1], vec![1]]
    );

    let session_trace = Arc::new(Mutex::new(Vec::new()));
    let execute_trace = Arc::clone(&session_trace);
    let session_cancelled = execute_flow_steps_with_policy(
        &root,
        Duration::from_secs(1),
        policy,
        &CancellationToken::new(),
        || true,
        move |step, _timeout, _token| -> ActionExecutionFuture<'static> {
            let trace = Arc::clone(&execute_trace);
            let mut label = String::new();
            if let Step::Click { selector } = &step {
                label.clone_from(selector);
            }
            Box::pin(async move {
                trace
                    .lock()
                    .expect("mock trace mutex should not be poisoned")
                    .push(label.clone());
                Err(SessionError::Cancelled)
            })
        },
    )
    .await;
    assert!(trace_snapshot(&session_trace).is_empty());
    assert_ne!(session_cancelled.terminal, FlowTermination::Completed);
    assert_eq!(
        session_cancelled
            .steps
            .first()
            .and_then(|step| step.cancellation),
        Some(FlowCancellationCause::Session)
    );
}

#[tokio::test]
async fn cancelled_child_flow_authority_skips_its_remaining_leaves_under_continue() {
    let child_token = CancellationToken::new();
    child_token.cancel();
    let child = Flow::new([
        click("child_cancelled_leaf").on_cancellation(Continuation::Continue),
        click("child_forbidden_sibling").on_cancellation(Continuation::Continue),
    ])
    .on_cancellation(Continuation::Continue);
    let child_step = Step::from(child)
        .with_cancellation(&child_token)
        .on_cancellation(Continuation::Continue);
    let root =
        Flow::new([child_step, click("parent_sibling")]).on_cancellation(Continuation::Continue);
    let root_token = CancellationToken::new();
    let trace = Arc::new(Mutex::new(Vec::new()));
    let execute_trace = Arc::clone(&trace);
    let result = execute_flow_steps_with_policy(
        &root,
        Duration::from_secs(1),
        FlowPolicy::default(),
        &root_token,
        || false,
        move |step, _timeout, _action_token| -> ActionExecutionFuture<'static> {
            let trace = Arc::clone(&execute_trace);
            let mut label = String::new();
            if let Step::Click { selector } = &step {
                label.clone_from(selector);
            }
            Box::pin(async move {
                trace
                    .lock()
                    .expect("mock trace mutex should not be poisoned")
                    .push(label.clone());
                Ok(receipt(&label, OperationStatus::Observed))
            })
        },
    )
    .await;

    assert_eq!(trace_snapshot(&trace), vec!["parent_sibling".to_owned()]);
    assert_eq!(result.terminal, FlowTermination::CompletedWithIssues);
    assert_eq!(result.steps.len(), 2);
    assert_eq!(result.steps[0].flow_path, [0, 0]);
    assert_eq!(
        result.steps[0].cancellation,
        Some(FlowCancellationCause::Step)
    );
    assert_eq!(result.steps[0].cancelled_flow, Some(vec![0]));
    assert_eq!(result.steps[1].flow_path, [1]);
    assert_eq!(result.skipped_steps.len(), 1);
    assert_eq!(result.skipped_steps[0].flow_path, [0, 1]);
    assert_eq!(result.skipped_steps[0].stopped_by, [0, 0]);
    assert_eq!(result.skipped_steps[0].scope, StopScope::CurrentFlow);
    assert!(result.stop_reason.is_none());
    assert!(!root_token.is_cancelled());
}

#[tokio::test]
async fn cancelling_outer_child_in_grandchild_skips_its_whole_subtree_only() {
    let outer_child_token = CancellationToken::new();
    let grandchild = Flow::new([
        click("grandchild_running").on_cancellation(Continuation::Continue),
        click("grandchild_forbidden_sibling").on_cancellation(Continuation::Continue),
    ])
    .on_cancellation(Continuation::Continue);
    let outer_child = Flow::new([grandchild.into(), click("middle_forbidden_sibling")])
        .on_cancellation(Continuation::Continue);
    let outer_child_step = Step::from(outer_child)
        .with_cancellation(&outer_child_token)
        .on_cancellation(Continuation::Continue);
    let root = Flow::new([outer_child_step, click("root_sibling")])
        .on_cancellation(Continuation::Continue);
    let root_token = CancellationToken::new();
    let trace = Arc::new(Mutex::new(Vec::new()));
    let execute_trace = Arc::clone(&trace);
    let (started_tx, started_rx) = tokio::sync::oneshot::channel();
    let mut started_tx = Some(started_tx);
    let execution_root_token = root_token.clone();
    let execute = move |step: Step,
                        _timeout: Duration,
                        action_token: CancellationToken|
          -> ActionExecutionFuture<'static> {
        let trace = Arc::clone(&execute_trace);
        let mut label = String::new();
        if let Step::Click { selector } = &step {
            label.clone_from(selector);
        }
        let started = if label == "grandchild_running" {
            started_tx.take()
        } else {
            None
        };
        Box::pin(async move {
            trace
                .lock()
                .expect("mock trace mutex should not be poisoned")
                .push(label.clone());
            if let Some(started) = started {
                let _ = started.send(());
            }
            if label == "grandchild_running" {
                action_token.cancelled().await;
                Err(SessionError::Cancelled)
            } else {
                Ok(receipt(&label, OperationStatus::Observed))
            }
        })
    };
    let execution = tokio::spawn(async move {
        execute_flow_steps_with_policy(
            &root,
            Duration::from_secs(1),
            FlowPolicy::default(),
            &execution_root_token,
            || false,
            execute,
        )
        .await
    });

    tokio::time::timeout(Duration::from_secs(1), started_rx)
        .await
        .expect("grandchild action should start")
        .expect("grandchild start notification should arrive");
    outer_child_token.cancel();
    let result = tokio::time::timeout(Duration::from_secs(1), execution)
        .await
        .expect("outer Flow cancellation should stop its subtree")
        .expect("mocked executor task should finish");

    assert_eq!(
        trace_snapshot(&trace),
        vec!["grandchild_running".to_owned(), "root_sibling".to_owned()]
    );
    assert_eq!(result.terminal, FlowTermination::CompletedWithIssues);
    assert_eq!(result.steps.len(), 2);
    assert_eq!(result.steps[0].flow_path, [0, 0, 0]);
    assert_eq!(
        result.steps[0].cancellation,
        Some(FlowCancellationCause::Step)
    );
    assert_eq!(result.steps[0].cancelled_flow, Some(vec![0]));
    assert_eq!(result.steps[1].flow_path, [1]);
    assert_eq!(
        result
            .skipped_steps
            .iter()
            .map(|step| step.flow_path.clone())
            .collect::<Vec<_>>(),
        vec![vec![0, 0, 1], vec![0, 1]]
    );
    assert!(
        result
            .skipped_steps
            .iter()
            .all(|step| step.scope == StopScope::CurrentFlow)
    );
    assert!(result.stop_reason.is_none());
    assert!(!root_token.is_cancelled());
}

#[tokio::test]
async fn closed_authority_is_an_unsafe_hard_stop_under_continue() {
    let flow = Flow::new([click("closed_authority"), click("forbidden_after_close")]);
    let root_token = CancellationToken::new();
    let trace = Arc::new(Mutex::new(Vec::new()));
    let execute_trace = Arc::clone(&trace);
    let result = execute_flow_steps_with_policy(
        &flow,
        Duration::from_secs(1),
        FlowPolicy::default(),
        &root_token,
        || false,
        move |step, _timeout, _action_token| -> ActionExecutionFuture<'static> {
            let trace = Arc::clone(&execute_trace);
            let mut label = String::new();
            if let Step::Click { selector } = &step {
                label.clone_from(selector);
            }
            Box::pin(async move {
                trace
                    .lock()
                    .expect("mock trace mutex should not be poisoned")
                    .push(label.clone());
                if label == "closed_authority" {
                    Err(SessionError::Closed)
                } else {
                    Ok(receipt(&label, OperationStatus::Observed))
                }
            })
        },
    )
    .await;

    assert_eq!(trace_snapshot(&trace), vec!["closed_authority".to_owned()]);
    assert_eq!(result.terminal, FlowTermination::Failed);
    assert_eq!(result.steps.len(), 1);
    assert_eq!(result.steps[0].failure, Some(FlowFailureCause::Execution));
    assert_eq!(result.steps[0].receipt.status, OperationStatus::Rejected);
    assert_eq!(result.steps[0].cancellation, None);
    assert_eq!(
        result.stop_reason.as_ref().map(|reason| reason.cause),
        Some(FlowStopCause::UnsafeState)
    );
    assert_eq!(
        result
            .stop_reason
            .as_ref()
            .and_then(|reason| reason.continuation),
        None
    );
    assert_eq!(result.skipped_steps.len(), 1);
    assert_eq!(result.skipped_steps[0].flow_path, [1]);
    assert_eq!(result.skipped_steps[0].cause, FlowStopCause::UnsafeState);
    assert_eq!(result.skipped_steps[0].scope, StopScope::Invocation);
    assert!(!root_token.is_cancelled());
}
