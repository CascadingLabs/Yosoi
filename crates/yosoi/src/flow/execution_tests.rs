use super::{
    execute_action, execute_flow_steps, resolve_action_timeout, resolve_flow_timeout,
    resolve_root_default,
};
use crate::{
    automation_record::{OperationReceipt, OperationStatus},
    flow::{Flow, FlowTermination, Step},
    policy::Policy,
    session::{SessionError, SessionPolicy},
    timing,
};
use std::time::Duration;

async fn simulated_control_call(duration: Duration) -> Result<(), SessionError> {
    let remaining = timing::remaining().ok_or(SessionError::InvalidInput)?;
    timing::bound(remaining, tokio::time::sleep(duration))
        .await
        .map_err(|_| SessionError::Deadline)
}

#[tokio::test(start_paused = true)]
async fn longer_nested_flow_runs_past_parent_and_sibling_restores_parent_timeout() {
    let parent_timeout = Duration::from_millis(5_000);
    let parent = Flow::new([Step::Screenshot]).timeout(5_000);
    let child = Flow::new([Step::Screenshot]).timeout(30_000);
    let policy_fallback = Duration::from_millis(10_000);

    assert_eq!(
        resolve_flow_timeout(&Flow::new([]), policy_fallback),
        policy_fallback
    );
    assert_eq!(
        resolve_flow_timeout(&parent, policy_fallback),
        parent_timeout
    );
    let child_timeout = resolve_flow_timeout(&child, parent_timeout);
    assert_eq!(child_timeout, Duration::from_secs(30));

    let child_started = tokio::time::Instant::now();
    execute_action(
        child_timeout,
        simulated_control_call(Duration::from_secs(6)),
    )
    .await
    .expect("child action should exceed the parent scope and complete");
    assert!(child_started.elapsed() >= Duration::from_secs(6));

    let sibling_timeout = resolve_action_timeout(&Step::Screenshot, parent_timeout);
    assert_eq!(sibling_timeout, parent_timeout);
    let sibling = execute_action(
        sibling_timeout,
        simulated_control_call(Duration::from_secs(6)),
    )
    .await;
    assert!(matches!(sibling, Err(SessionError::Deadline)));
}

#[tokio::test(start_paused = true)]
async fn native_nested_execution_keeps_child_receipt_path_and_parent_sibling_budget() {
    let child = Flow::new([Step::Click {
        selector: "#child".to_owned(),
    }])
    .timeout(30_000);
    let parent = Flow::new([child.into(), Step::Screenshot]).timeout(5_000);
    let started = tokio::time::Instant::now();

    let (steps, terminal) =
        execute_flow_steps(&parent, Duration::from_secs(10), |step, timeout| {
            Box::pin(async move {
                let operation_duration = match step {
                    Step::Click { .. } => Duration::from_secs(6),
                    Step::Screenshot => Duration::from_secs(6),
                    _ => return Err(SessionError::InvalidInput),
                };
                execute_action(timeout, async move {
                    simulated_control_call(operation_duration).await?;
                    Ok(OperationReceipt {
                        id: "mock-operation".to_owned(),
                        kind: "mock".to_owned(),
                        status: OperationStatus::Observed,
                        result: None,
                        observation: None,
                        error: None,
                    })
                })
                .await
            })
        })
        .await;

    assert_eq!(started.elapsed(), Duration::from_secs(11));
    assert_eq!(terminal, FlowTermination::CompletedWithIssues);
    assert_eq!(steps.len(), 2);
    assert_eq!(
        steps.first().map(|step| step.flow_path.as_slice()),
        Some(&[0, 0][..])
    );
    assert_eq!(
        steps.get(1).map(|step| step.flow_path.as_slice()),
        Some(&[1][..])
    );
    assert_eq!(
        steps.first().map(|step| step.receipt.status),
        Some(OperationStatus::Observed)
    );
    assert_eq!(
        steps.get(1).map(|step| step.receipt.status),
        Some(OperationStatus::Rejected)
    );
}

#[tokio::test(start_paused = true)]
async fn three_depth_native_flow_inherits_and_restores_action_overrides() {
    let leaf = Flow::new([Step::Screenshot.timeout(30_000), Step::Screenshot]);
    let middle = Flow::new([leaf.into(), Step::Screenshot]).timeout(20_000);
    let root = Flow::new([middle.into(), Step::Screenshot]).timeout(5_000);
    let mut selected = Vec::new();
    let (steps, terminal) = execute_flow_steps(&root, Duration::from_secs(10), |_, timeout| {
        selected.push(timeout);
        Box::pin(async {
            Ok(OperationReceipt {
                id: "mock-operation".to_owned(),
                kind: "screenshot".to_owned(),
                status: OperationStatus::Observed,
                result: None,
                observation: None,
                error: None,
            })
        })
    })
    .await;
    assert_eq!(terminal, FlowTermination::Completed);
    assert_eq!(selected, [30, 20, 20, 5].map(Duration::from_secs));
    assert_eq!(
        steps
            .iter()
            .map(|step| step.flow_path.clone())
            .collect::<Vec<_>>(),
        [vec![0, 0, 0], vec![0, 0, 1], vec![0, 1], vec![1]]
    );
}

#[tokio::test(start_paused = true)]
async fn internal_action_phases_share_one_deadline() {
    let result = execute_action(Duration::from_secs(10), async {
        simulated_control_call(Duration::from_secs(6)).await?;
        simulated_control_call(Duration::from_secs(6)).await
    })
    .await;

    assert!(matches!(result, Err(SessionError::Deadline)));
}

#[tokio::test(start_paused = true)]
async fn concurrent_action_scopes_do_not_leak_deadlines() {
    let short = execute_action(Duration::from_secs(5), async {
        tokio::task::yield_now().await;
        timing::remaining().ok_or(SessionError::InvalidInput)
    });
    let long = execute_action(Duration::from_secs(30), async {
        tokio::task::yield_now().await;
        timing::remaining().ok_or(SessionError::InvalidInput)
    });
    let (short, long) = tokio::join!(short, long);
    let short = short.expect("short action should retain its own deadline");
    let long = long.expect("long action should retain its own deadline");

    assert_eq!(short, Duration::from_secs(5));
    assert_eq!(long, Duration::from_secs(30));
    assert!(long > short);
}

#[test]
fn bound_policy_overrides_session_policy_and_unbound_flow_inherits_session_policy() {
    let mut owning_policy = Policy::default();
    owning_policy.default_action_timeout_ms = 20_000;
    let session_policy_default = Duration::from_millis(owning_policy.default_action_timeout_ms);
    let session_policy_direct_work_default =
        Duration::from_millis(SessionPolicy::default().operation_timeout_ms);

    assert_eq!(
        resolve_root_default(None, session_policy_default),
        Duration::from_secs(20)
    );
    assert_eq!(
        resolve_root_default(Some(&Policy::default()), session_policy_default),
        Duration::from_secs(10)
    );
    assert_eq!(session_policy_direct_work_default, Duration::from_secs(10));
}

#[test]
fn precedence_uses_policy_then_nearest_flow_then_action_timeout() {
    let policy_fallback = Duration::from_millis(10_000);
    let parent = Flow::new([]).timeout(5_000);
    let child_without_timeout = Flow::new([]);
    let child_override = Flow::new([]).timeout(20_000);

    assert_eq!(
        resolve_flow_timeout(&Flow::new([]), policy_fallback),
        policy_fallback
    );
    assert_eq!(
        resolve_flow_timeout(&parent, policy_fallback),
        Duration::from_secs(5)
    );
    assert_eq!(
        resolve_flow_timeout(
            &child_without_timeout,
            resolve_flow_timeout(&parent, policy_fallback)
        ),
        Duration::from_secs(5)
    );
    assert_eq!(
        resolve_flow_timeout(
            &child_override,
            resolve_flow_timeout(&parent, policy_fallback)
        ),
        Duration::from_secs(20)
    );
    assert_eq!(
        resolve_action_timeout(&Step::Screenshot.timeout(1_000), Duration::from_secs(5)),
        Duration::from_secs(1)
    );
    assert_eq!(
        resolve_action_timeout(&Step::Screenshot.timeout(30_000), Duration::from_secs(5)),
        Duration::from_secs(30)
    );
}
