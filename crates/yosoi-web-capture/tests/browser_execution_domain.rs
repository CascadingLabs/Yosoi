#![allow(
    clippy::panic_in_result_fn,
    reason = "test assertions provide clearer receipt invariant diagnostics"
)]

use std::{
    error::Error,
    io,
    num::{NonZeroU32, NonZeroU64},
};

use chrono::{DateTime, Duration as WallDuration, Utc};
use serde_json::Value;
use yosoi_types::{ActivityId, CaptureId};
use yosoi_web_capture::{
    BrowserCleanupDeadline, BrowserContextCleanupDisposition, BrowserContextLease,
    BrowserContextLeaseId, BrowserContextTotalLimit, BrowserContextsPerProcessLimit,
    BrowserExecutionAccountingReceipt, BrowserExecutionAdmissionReceipt,
    BrowserExecutionCleanupReceipt, BrowserExecutionId, BrowserExecutionLease,
    BrowserExecutionLimits, BrowserExecutionManagerId, BrowserExecutionPreAdmissionOutcome,
    BrowserExecutionReceipt, BrowserExecutionReceiptError, BrowserExecutionScope,
    BrowserExecutionTerminalReason, BrowserExecutionTerminalReceipt,
    BrowserProcessCleanupDisposition, BrowserProcessGeneration, BrowserProcessLimit,
    BrowserProcessSlotId, BrowserProcessSlotLease, BrowserProfileCheckpointId,
    BrowserProfileCheckpointIdentity, BrowserProfileChildId, BrowserProfileChildIdentity,
    BrowserProfileForkError, BrowserProfileForkFailureFacts, BrowserProfileForkFailureReason,
    BrowserProfileForkFailureReceipt, BrowserProfileForkReceipt, BrowserProfileForkRequest,
    BrowserProfileForkSuccessFacts, BrowserProfileId, BrowserProfileLeaseGenerationRegistry,
    BrowserProfileLeaseId, BrowserProfileLeaseReceipt, BrowserProfileLeaseScope,
    BrowserProfileLineageId, BrowserProfileLineageIdentity, BrowserProfileOwnerId,
    BrowserQueueDepthLimit, BrowserQueueWaitLimit, BrowserRecycleThreshold, BrowserSessionLease,
    BrowserSessionLeaseId, BrowserTabLease, BrowserTabLeaseId, BrowserTabTotalLimit,
    BrowserTabsPerSessionLimit, ResolvedBrowserProfileForkLimits,
};

fn limits() -> Result<BrowserExecutionLimits, Box<dyn Error>> {
    Ok(BrowserExecutionLimits::new(
        BrowserProcessLimit::new(NonZeroU32::new(2).ok_or("nonzero literal")?),
        BrowserContextTotalLimit::new(NonZeroU32::new(3).ok_or("nonzero literal")?),
        BrowserContextsPerProcessLimit::new(NonZeroU32::new(2).ok_or("nonzero literal")?),
        BrowserTabTotalLimit::new(NonZeroU32::new(4).ok_or("nonzero literal")?),
        BrowserTabsPerSessionLimit::new(NonZeroU32::new(2).ok_or("nonzero literal")?),
        BrowserQueueDepthLimit::new(NonZeroU32::new(4).ok_or("nonzero literal")?),
        BrowserQueueWaitLimit::new(NonZeroU64::new(100).ok_or("nonzero literal")?),
        BrowserCleanupDeadline::new(NonZeroU64::new(200).ok_or("nonzero literal")?),
        BrowserRecycleThreshold::new(NonZeroU32::new(5).ok_or("nonzero literal")?),
    )?)
}

fn admission() -> Result<BrowserExecutionAdmissionReceipt, Box<dyn Error>> {
    let process = BrowserProcessSlotLease::new(
        BrowserExecutionManagerId::random(),
        BrowserProcessSlotId::random(),
        BrowserProcessGeneration::new(NonZeroU64::MIN),
    );
    let execution = BrowserExecutionLease::new(process, BrowserExecutionId::random());
    let context = BrowserContextLease::new(execution.clone(), BrowserContextLeaseId::random());
    let session = BrowserSessionLease::new(context.clone(), BrowserSessionLeaseId::random());
    let tab = BrowserTabLease::new(session.clone(), BrowserTabLeaseId::random());
    Ok(BrowserExecutionAdmissionReceipt::new(
        BrowserExecutionScope::Independent,
        execution,
        context,
        session,
        tab,
    )?)
}

fn terminal(
    admission: BrowserExecutionAdmissionReceipt,
    context: BrowserContextCleanupDisposition,
    process: BrowserProcessCleanupDisposition,
    reason: BrowserExecutionTerminalReason,
) -> Result<BrowserExecutionTerminalReceipt, BrowserExecutionReceiptError> {
    let cleanup = BrowserExecutionCleanupReceipt::new(admission.clone(), context, process);
    BrowserExecutionTerminalReceipt::new(admission, cleanup, reason)
}

#[allow(clippy::too_many_arguments)]
fn terminal_accounting(
    admission: BrowserExecutionAdmissionReceipt,
    active_processes: u32,
    active_contexts_total: u32,
    active_contexts_in_process: u32,
    active_tabs_total: u32,
    active_tabs_in_session: u32,
    completed: u32,
) -> Result<BrowserExecutionAccountingReceipt, Box<dyn Error>> {
    Ok(BrowserExecutionAccountingReceipt::terminal(
        admission,
        limits()?,
        active_processes,
        active_contexts_total,
        active_contexts_in_process,
        active_tabs_total,
        active_tabs_in_session,
        0,
        completed,
    )?)
}

fn receipt_for(
    context: BrowserContextCleanupDisposition,
    process: BrowserProcessCleanupDisposition,
    reason: BrowserExecutionTerminalReason,
) -> Result<BrowserExecutionReceipt, Box<dyn Error>> {
    let admission = admission()?;
    let terminal = terminal(admission.clone(), context, process, reason)?;
    let active_processes = u32::from(process != BrowserProcessCleanupDisposition::Completed);
    Ok(BrowserExecutionReceipt::new(
        CaptureId::random(),
        terminal,
        terminal_accounting(admission, active_processes, 0, 0, 0, 0, 1)?,
    )?)
}

#[test]
fn every_terminal_reason_is_secret_safe_and_round_trips() -> Result<(), Box<dyn Error>> {
    let cases = [
        (
            BrowserExecutionTerminalReason::Completed,
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::WarmRetained,
        ),
        (
            BrowserExecutionTerminalReason::CallerCancelled,
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::WarmRetained,
        ),
        (
            BrowserExecutionTerminalReason::SystemInterrupted,
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::WarmRetained,
        ),
        (
            BrowserExecutionTerminalReason::DeadlineExceeded,
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::WarmRetained,
        ),
        (
            BrowserExecutionTerminalReason::ProviderDisconnected,
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::WarmRetained,
        ),
        (
            BrowserExecutionTerminalReason::ProviderUnavailable,
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::WarmRetained,
        ),
        (
            BrowserExecutionTerminalReason::ObservationLimitExceeded,
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::WarmRetained,
        ),
        (
            BrowserExecutionTerminalReason::TabCloseFailed,
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::WarmRetained,
        ),
        (
            BrowserExecutionTerminalReason::ContextCleanupFailed,
            BrowserContextCleanupDisposition::Failed,
            BrowserProcessCleanupDisposition::Completed,
        ),
        (
            BrowserExecutionTerminalReason::ContextCleanupDeadlineExceeded,
            BrowserContextCleanupDisposition::DeadlineExceeded,
            BrowserProcessCleanupDisposition::Completed,
        ),
        (
            BrowserExecutionTerminalReason::ProcessCleanupFailed,
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::Failed,
        ),
        (
            BrowserExecutionTerminalReason::ProcessCleanupDeadlineExceeded,
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::DeadlineExceeded,
        ),
        (
            BrowserExecutionTerminalReason::InternalInvariantFailure,
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::WarmRetained,
        ),
        (
            BrowserExecutionTerminalReason::ProviderFailure,
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::WarmRetained,
        ),
    ];
    for (reason, context, process) in cases {
        let receipt = receipt_for(context, process, reason)?;
        let encoded = serde_json::to_string(&receipt)?;
        let decoded = serde_json::from_str::<BrowserExecutionReceipt>(&encoded)?;
        if decoded != receipt || decoded.terminal().reason() != reason {
            return Err(io::Error::other("terminal reason changed in JSON round-trip").into());
        }
        for forbidden in ["authorization", "cookie", "https://", "diagnostic"] {
            if encoded.contains(forbidden) {
                return Err(io::Error::other("execution receipt exposed provider data").into());
            }
        }
    }
    Ok(())
}

#[test]
fn terminal_reason_and_cleanup_mismatches_fail_closed() -> Result<(), Box<dyn Error>> {
    let mismatches = [
        (
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::Completed,
            BrowserExecutionTerminalReason::ContextCleanupFailed,
            BrowserExecutionReceiptError::ContextCleanupReasonMismatch,
        ),
        (
            BrowserContextCleanupDisposition::Failed,
            BrowserProcessCleanupDisposition::Completed,
            BrowserExecutionTerminalReason::ContextCleanupDeadlineExceeded,
            BrowserExecutionReceiptError::ContextCleanupReasonMismatch,
        ),
        (
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::Completed,
            BrowserExecutionTerminalReason::ProcessCleanupFailed,
            BrowserExecutionReceiptError::ProcessCleanupReasonMismatch,
        ),
        (
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::Failed,
            BrowserExecutionTerminalReason::ProcessCleanupDeadlineExceeded,
            BrowserExecutionReceiptError::ProcessCleanupReasonMismatch,
        ),
        (
            BrowserContextCleanupDisposition::Failed,
            BrowserProcessCleanupDisposition::Completed,
            BrowserExecutionTerminalReason::Completed,
            BrowserExecutionReceiptError::CompletionWithoutCompletedContextCleanup,
        ),
        (
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::Failed,
            BrowserExecutionTerminalReason::Completed,
            BrowserExecutionReceiptError::CompletionWithUnsuccessfulProcessCleanup,
        ),
    ];
    for (context, process, reason, expected) in mismatches {
        if terminal(admission()?, context, process, reason) != Err(expected) {
            return Err(io::Error::other("terminal cleanup contradiction was accepted").into());
        }
    }

    let valid = terminal(
        admission()?,
        BrowserContextCleanupDisposition::Failed,
        BrowserProcessCleanupDisposition::Completed,
        BrowserExecutionTerminalReason::ProviderFailure,
    )?;
    let valid_json = serde_json::to_value(valid)?;
    let mut invalid = valid_json.clone();
    invalid["reason"] = Value::String("completed".to_owned());
    if serde_json::from_value::<BrowserExecutionTerminalReceipt>(invalid).is_ok() {
        return Err(io::Error::other("serde accepted contradictory terminal cleanup").into());
    }
    let mut unknown_reason = valid_json.clone();
    unknown_reason["reason"] = Value::String("provider_diagnostic".to_owned());
    if serde_json::from_value::<BrowserExecutionTerminalReceipt>(unknown_reason).is_ok() {
        return Err(io::Error::other("serde accepted an open-ended terminal reason").into());
    }
    let mut raw_diagnostic = valid_json;
    raw_diagnostic["provider_diagnostic"] = Value::String("secret provider text".to_owned());
    if serde_json::from_value::<BrowserExecutionTerminalReceipt>(raw_diagnostic).is_ok() {
        return Err(io::Error::other("serde accepted raw terminal diagnostics").into());
    }
    Ok(())
}

#[test]
fn accounting_rejects_impossible_global_and_lease_local_states() -> Result<(), Box<dyn Error>> {
    let cases = [
        (
            BrowserExecutionAccountingReceipt::terminal(
                admission()?,
                limits()?,
                1,
                0,
                0,
                0,
                0,
                0,
                0,
            ),
            BrowserExecutionReceiptError::TerminalExecutionNotCounted,
        ),
        (
            BrowserExecutionAccountingReceipt::terminal(
                admission()?,
                limits()?,
                0,
                1,
                1,
                0,
                0,
                0,
                1,
            ),
            BrowserExecutionReceiptError::ContextsWithoutActiveProcess,
        ),
        (
            BrowserExecutionAccountingReceipt::terminal(
                admission()?,
                limits()?,
                1,
                3,
                2,
                3,
                0,
                0,
                1,
            ),
            BrowserExecutionReceiptError::ContextsExceedActiveProcessCapacity,
        ),
        (
            BrowserExecutionAccountingReceipt::terminal(
                admission()?,
                limits()?,
                2,
                3,
                2,
                2,
                0,
                0,
                1,
            ),
            BrowserExecutionReceiptError::ActiveContextsExceedActiveTabs,
        ),
        (
            BrowserExecutionAccountingReceipt::terminal(
                admission()?,
                limits()?,
                1,
                0,
                0,
                1,
                0,
                0,
                1,
            ),
            BrowserExecutionReceiptError::TabsWithoutActiveContext,
        ),
        (
            BrowserExecutionAccountingReceipt::terminal(
                admission()?,
                limits()?,
                1,
                1,
                0,
                1,
                1,
                0,
                1,
            ),
            BrowserExecutionReceiptError::SessionTabsWithoutActiveContext,
        ),
        (
            BrowserExecutionAccountingReceipt::terminal(
                admission()?,
                limits()?,
                1,
                1,
                1,
                1,
                1,
                0,
                1,
            ),
            BrowserExecutionReceiptError::TerminalSessionTabsRemain,
        ),
    ];
    for (result, expected) in cases {
        if result != Err(expected) {
            return Err(io::Error::other("impossible terminal accounting was accepted").into());
        }
    }

    let admission_result =
        BrowserExecutionAccountingReceipt::new(admission()?, limits()?, 1, 1, 1, 1, 1, 0, 6);
    if admission_result != Err(BrowserExecutionReceiptError::RecycleThresholdExceeded) {
        return Err(io::Error::other("admission above recycle threshold was accepted").into());
    }
    terminal_accounting(admission()?, 1, 1, 0, 1, 0, 6)?;
    Ok(())
}

#[test]
fn receipt_enforces_cleanup_accounting_coherence_without_rejecting_other_resources()
-> Result<(), Box<dyn Error>> {
    let make =
        |context, process, active_processes, contexts_total, contexts_in_process, completed| {
            let admission = admission()?;
            let terminal = terminal(
                admission.clone(),
                context,
                process,
                BrowserExecutionTerminalReason::ProviderFailure,
            )?;
            let accounting = terminal_accounting(
                admission,
                active_processes,
                contexts_total,
                contexts_in_process,
                u32::from(contexts_total > 0),
                0,
                completed,
            )?;
            Ok::<_, Box<dyn Error>>(BrowserExecutionReceipt::new(
                CaptureId::random(),
                terminal,
                accounting,
            ))
        };

    let invalid = [
        make(
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::WarmRetained,
            0,
            0,
            0,
            1,
        )?,
        make(
            BrowserContextCleanupDisposition::Failed,
            BrowserProcessCleanupDisposition::WarmRetained,
            1,
            0,
            0,
            1,
        )?,
        make(
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::Completed,
            1,
            1,
            1,
            1,
        )?,
        make(
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::Failed,
            0,
            0,
            0,
            1,
        )?,
        make(
            BrowserContextCleanupDisposition::Completed,
            BrowserProcessCleanupDisposition::Failed,
            1,
            1,
            1,
            1,
        )?,
    ];
    let expected = [
        BrowserExecutionReceiptError::CleanupRequiresActiveProcess,
        BrowserExecutionReceiptError::UnsuccessfulContextCleanupWarmRetained,
        BrowserExecutionReceiptError::ClosedProcessHasActiveContexts,
        BrowserExecutionReceiptError::CleanupRequiresActiveProcess,
        BrowserExecutionReceiptError::ClosedProcessHasActiveContexts,
    ];
    for (result, expected) in invalid.into_iter().zip(expected) {
        if result != Err(expected) {
            return Err(io::Error::other("cleanup/accounting contradiction was accepted").into());
        }
    }

    // The admitted generation is closed, while unrelated global resources may
    // remain active. Failed context disposal plus successful process close is
    // also retained exactly rather than rewritten into context success.
    make(
        BrowserContextCleanupDisposition::Failed,
        BrowserProcessCleanupDisposition::Completed,
        1,
        1,
        0,
        1,
    )??;
    make(
        BrowserContextCleanupDisposition::Completed,
        BrowserProcessCleanupDisposition::Failed,
        2,
        1,
        0,
        7,
    )??;
    Ok(())
}

#[test]
fn receipt_serde_revalidates_accounting_and_bindings() -> Result<(), Box<dyn Error>> {
    let receipt = receipt_for(
        BrowserContextCleanupDisposition::Completed,
        BrowserProcessCleanupDisposition::WarmRetained,
        BrowserExecutionTerminalReason::Completed,
    )?;
    let mut zero_completed = serde_json::to_value(&receipt)?;
    zero_completed["accounting"]["completed_executions_since_recycle"] = Value::from(0);
    if serde_json::from_value::<BrowserExecutionReceipt>(zero_completed).is_ok() {
        return Err(io::Error::other("serde accepted an uncounted terminal execution").into());
    }
    let mut tabs_remain = serde_json::to_value(&receipt)?;
    tabs_remain["accounting"]["active_contexts_total"] = Value::from(1);
    tabs_remain["accounting"]["active_contexts_in_process"] = Value::from(1);
    tabs_remain["accounting"]["active_tabs_total"] = Value::from(1);
    tabs_remain["accounting"]["active_tabs_in_session"] = Value::from(1);
    if serde_json::from_value::<BrowserExecutionReceipt>(tabs_remain).is_ok() {
        return Err(io::Error::other("serde accepted lease-local terminal tabs").into());
    }

    let mut warm_without_process = serde_json::to_value(&receipt)?;
    warm_without_process["accounting"]["active_processes"] = Value::from(0);
    let mut unsuccessful_context_warm = serde_json::to_value(&receipt)?;
    unsuccessful_context_warm["terminal"]["reason"] = Value::String("provider_failure".to_owned());
    unsuccessful_context_warm["terminal"]["cleanup"]["context"] =
        Value::String("failed".to_owned());
    let closed = receipt_for(
        BrowserContextCleanupDisposition::Failed,
        BrowserProcessCleanupDisposition::Completed,
        BrowserExecutionTerminalReason::ContextCleanupFailed,
    )?;
    let mut closed_with_local_context = serde_json::to_value(closed)?;
    closed_with_local_context["accounting"]["active_processes"] = Value::from(1);
    closed_with_local_context["accounting"]["active_contexts_total"] = Value::from(1);
    closed_with_local_context["accounting"]["active_contexts_in_process"] = Value::from(1);
    let failed_close = receipt_for(
        BrowserContextCleanupDisposition::Completed,
        BrowserProcessCleanupDisposition::Failed,
        BrowserExecutionTerminalReason::ProcessCleanupFailed,
    )?;
    let mut failed_close_without_process = serde_json::to_value(failed_close)?;
    failed_close_without_process["accounting"]["active_processes"] = Value::from(0);
    for invalid in [
        warm_without_process,
        unsuccessful_context_warm,
        closed_with_local_context,
        failed_close_without_process,
    ] {
        if serde_json::from_value::<BrowserExecutionReceipt>(invalid).is_ok() {
            return Err(io::Error::other("serde accepted cleanup/accounting contradiction").into());
        }
    }

    let second_admission = admission()?;
    let mut cross_admission = serde_json::to_value(&receipt)?;
    cross_admission["accounting"]["admission"] = serde_json::to_value(second_admission)?;
    if serde_json::from_value::<BrowserExecutionReceipt>(cross_admission).is_ok() {
        return Err(io::Error::other("serde accepted cross-admission accounting").into());
    }
    let mut wrong_phase = serde_json::to_value(&receipt)?;
    wrong_phase["accounting"]["phase"] = Value::String("admission".to_owned());
    wrong_phase["accounting"]["active_contexts_total"] = Value::from(1);
    wrong_phase["accounting"]["active_contexts_in_process"] = Value::from(1);
    wrong_phase["accounting"]["active_tabs_total"] = Value::from(1);
    wrong_phase["accounting"]["active_tabs_in_session"] = Value::from(1);
    if serde_json::from_value::<BrowserExecutionReceipt>(wrong_phase).is_ok() {
        return Err(io::Error::other("serde accepted admission accounting as terminal").into());
    }
    Ok(())
}

#[test]
fn constructors_reject_cross_execution_lease_scopes() {
    let process = BrowserProcessSlotLease::new(
        BrowserExecutionManagerId::random(),
        BrowserProcessSlotId::random(),
        BrowserProcessGeneration::new(NonZeroU64::MIN),
    );
    let admitted_execution =
        BrowserExecutionLease::new(process.clone(), BrowserExecutionId::random());
    let foreign_execution = BrowserExecutionLease::new(process, BrowserExecutionId::random());
    let foreign_context =
        BrowserContextLease::new(foreign_execution, BrowserContextLeaseId::random());
    let session =
        BrowserSessionLease::new(foreign_context.clone(), BrowserSessionLeaseId::random());
    let tab = BrowserTabLease::new(session.clone(), BrowserTabLeaseId::random());

    assert!(matches!(
        BrowserExecutionAdmissionReceipt::new(
            BrowserExecutionScope::SessionGroup,
            admitted_execution,
            foreign_context,
            session,
            tab,
        ),
        Err(BrowserExecutionReceiptError::ContextOutsideExecution)
    ));
}

#[test]
fn limits_and_pre_admission_outcomes_fail_closed_and_round_trip() -> Result<(), Box<dyn Error>> {
    let zero_processes = r#"{
        "processes": 0, "contexts_total": 2, "contexts_per_process": 2,
        "tabs_total": 3, "tabs_per_session": 2, "queue_depth": 4,
        "queue_wait": 100, "cleanup_deadline": 200, "recycle_threshold": 5
    }"#;
    if serde_json::from_str::<BrowserExecutionLimits>(zero_processes).is_ok() {
        return Err(io::Error::other("serde accepted zero process limit").into());
    }

    for outcome in [
        BrowserExecutionPreAdmissionOutcome::ProviderCleanupFailed,
        BrowserExecutionPreAdmissionOutcome::ProviderCleanupDeadlineExceeded,
    ] {
        let encoded = serde_json::to_string(&outcome)?;
        if serde_json::from_str::<BrowserExecutionPreAdmissionOutcome>(&encoded)? != outcome {
            return Err(io::Error::other("pre-admission outcome changed in serde").into());
        }
    }
    Ok(())
}

#[test]
fn execution_diagnostics_are_secret_safe() {
    let diagnostic = BrowserExecutionReceiptError::ContextOutsideExecution.to_string();
    for forbidden in ["api_key", "authorization", "cookie", "https://"] {
        assert!(!diagnostic.contains(forbidden));
    }
}

fn managed_profile_fork_request() -> Result<
    (
        BrowserProfileForkRequest,
        BrowserProfileLeaseGenerationRegistry,
        DateTime<Utc>,
    ),
    Box<dyn Error>,
> {
    let source_profile = BrowserProfileId::new("profile-source".to_owned())?;
    let generations = BrowserProfileLeaseGenerationRegistry::default();
    let generation = generations.next_generation(&source_profile)?;
    let acquired_at = DateTime::<Utc>::from_timestamp(1_800_000_000, 0)
        .ok_or("fixed test timestamp is invalid")?;
    let source_lease = BrowserProfileLeaseReceipt::new(
        source_profile,
        BrowserProfileLeaseId::random(),
        BrowserProfileOwnerId::random(),
        BrowserProfileLeaseScope::ExclusiveManagedBrowser,
        generation,
        acquired_at,
        acquired_at
            .checked_add_signed(WallDuration::seconds(60))
            .ok_or("source lease expiry overflowed")?,
    )?;
    let checkpoint = BrowserProfileCheckpointIdentity::new(
        BrowserProfileCheckpointId::new(ActivityId::random()),
        &source_lease,
    );
    let lineage = BrowserProfileLineageIdentity::new(
        BrowserProfileLineageId::new(ActivityId::random()),
        &checkpoint,
    );
    let children = ["profile-child-a", "profile-child-b"]
        .into_iter()
        .map(|profile_id| {
            Ok(BrowserProfileChildIdentity::new(
                BrowserProfileChildId::new(ActivityId::random()),
                BrowserProfileId::new(profile_id.to_owned())?,
                &lineage,
            ))
        })
        .collect::<Result<Vec<_>, Box<dyn Error>>>()?;
    let limits = ResolvedBrowserProfileForkLimits::new(2, 10_000)?;
    let requested_at = acquired_at
        .checked_add_signed(WallDuration::seconds(2))
        .ok_or("request timestamp overflowed")?;
    let child_expires_at = requested_at
        .checked_add_signed(WallDuration::seconds(3_600))
        .ok_or("child expiry overflowed")?;
    let request = BrowserProfileForkRequest::new(
        source_lease,
        checkpoint,
        lineage,
        children,
        limits,
        requested_at,
        child_expires_at,
    )?;
    Ok((request, generations, requested_at))
}

#[test]
fn profile_fork_receipt_binds_checkpoint_lineage_quota_and_child_expiry()
-> Result<(), Box<dyn Error>> {
    let (request, generations, requested_at) = managed_profile_fork_request()?;
    request.authorize_source(&generations, &requested_at)?;
    let child_profile_ids = request
        .children()
        .iter()
        .map(|child| child.profile_id().clone())
        .collect();
    let facts = BrowserProfileForkSuccessFacts::new(
        request.checkpoint().source_profile_id().clone(),
        child_profile_ids,
        9_500,
    );
    let finished_at = requested_at
        .checked_add_signed(WallDuration::seconds(2))
        .ok_or("finished timestamp overflowed")?;
    let receipt =
        BrowserProfileForkReceipt::from_success_facts(&request, facts, &generations, &finished_at)?;

    assert_eq!(receipt.children().len(), 2);
    assert_eq!(receipt.copied_bytes(), 9_500);
    assert_eq!(receipt.checkpoint(), request.checkpoint());
    assert_eq!(receipt.lineage(), request.lineage());
    assert_eq!(receipt.child_expires_at(), request.child_expires_at());
    let encoded = serde_json::to_string(&receipt)?;
    let decoded = serde_json::from_str::<BrowserProfileForkReceipt>(&encoded)?;
    assert_eq!(decoded, receipt);
    for forbidden in ["path", "cookie", "Cookies", "authorization", "https://"] {
        assert!(!encoded.contains(forbidden));
    }

    let mut over_quota = serde_json::to_value(&receipt)?;
    over_quota["copied_bytes"] = Value::from(10_001_u64);
    assert!(serde_json::from_value::<BrowserProfileForkReceipt>(over_quota).is_err());
    Ok(())
}

#[test]
fn profile_fork_rejects_stale_generation_and_invalid_resolved_quotas() -> Result<(), Box<dyn Error>>
{
    let (request, generations, requested_at) = managed_profile_fork_request()?;
    assert_eq!(
        request.authorize_source(&generations, &requested_at),
        Ok(())
    );
    generations.next_generation(request.checkpoint().source_profile_id())?;
    assert_eq!(
        request.authorize_source(&generations, &requested_at),
        Err(BrowserProfileForkError::StaleSourceGeneration)
    );

    assert_eq!(
        ResolvedBrowserProfileForkLimits::new(0, 1),
        Err(BrowserProfileForkError::InvalidMaximumCopies)
    );
    assert_eq!(
        ResolvedBrowserProfileForkLimits::new(17, 1),
        Err(BrowserProfileForkError::InvalidMaximumCopies)
    );
    assert_eq!(
        ResolvedBrowserProfileForkLimits::new(2, 0),
        Err(BrowserProfileForkError::InvalidAggregateByteQuota)
    );

    let source_lease = request.source_lease().clone();
    let too_small_limits = ResolvedBrowserProfileForkLimits::new(1, 10_000)?;
    assert_eq!(
        BrowserProfileForkRequest::new(
            source_lease,
            request.checkpoint().clone(),
            request.lineage().clone(),
            request.children().to_vec(),
            too_small_limits,
            requested_at,
            *request.child_expires_at(),
        )
        .map(|_| ()),
        Err(BrowserProfileForkError::ChildCountExceedsMaximum)
    );
    Ok(())
}

#[test]
fn profile_fork_failure_receipt_maps_only_neutral_facts() -> Result<(), Box<dyn Error>> {
    let (request, _, requested_at) = managed_profile_fork_request()?;
    let failed_at = requested_at
        .checked_add_signed(WallDuration::seconds(1))
        .ok_or("failure timestamp overflowed")?;
    let facts = BrowserProfileForkFailureFacts::new(
        BrowserProfileForkFailureReason::AggregateByteQuotaExceeded,
        Some(1),
        10_000,
        Some(10_001),
        true,
    );
    let receipt =
        BrowserProfileForkFailureReceipt::from_failure_facts(&request, facts, &failed_at)?;
    assert_eq!(
        receipt.facts().reason(),
        BrowserProfileForkFailureReason::AggregateByteQuotaExceeded
    );
    assert_eq!(receipt.facts().child_index(), Some(1));
    assert!(receipt.facts().cleanup_succeeded());

    let encoded = serde_json::to_string(&receipt)?;
    let decoded = serde_json::from_str::<BrowserProfileForkFailureReceipt>(&encoded)?;
    assert_eq!(decoded, receipt);
    for forbidden in ["path", "cookie", "Cookies", "authorization", "https://"] {
        assert!(!encoded.contains(forbidden));
    }

    let inconsistent_facts = BrowserProfileForkFailureFacts::new(
        BrowserProfileForkFailureReason::AggregateByteQuotaExceeded,
        Some(1),
        10_000,
        Some(10_000),
        true,
    );
    assert_eq!(
        BrowserProfileForkFailureReceipt::from_failure_facts(
            &request,
            inconsistent_facts,
            &failed_at,
        )
        .map(|_| ()),
        Err(BrowserProfileForkError::InvalidFailureFacts)
    );
    Ok(())
}
