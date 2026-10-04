use yosoi_types::{ActivityOutcome, ActivitySignal, ReasonCode, RetryDisposition};

use crate::{
    BrowserAdapterTerminal, BrowserByteDomain, BrowserProviderStop, BrowserTerminalKind, ByteLimit,
    CaptureTermination, ControllerStopReason, InterruptionEvidence, InterruptionInitiator,
    ResolvedBrowserCaptureSpec, SettlementEvidence,
};

use super::BrowserFinalizationError;

pub(super) fn convert_termination(
    terminal: &BrowserAdapterTerminal,
    spec: &ResolvedBrowserCaptureSpec,
    settlement: Option<&SettlementEvidence>,
) -> Result<CaptureTermination, BrowserFinalizationError> {
    Ok(match terminal.kind() {
        BrowserTerminalKind::DeadlineReached { .. } => CaptureTermination::DeadlineReached {
            maximum_elapsed: spec.observation().limits().maximum_elapsed(),
        },
        BrowserTerminalKind::EventLimitReached => CaptureTermination::EventLimitReached {
            event_limit: spec.observation().limits().event_limit().ok_or(
                BrowserFinalizationError::Invariant("event terminal without limit"),
            )?,
        },
        BrowserTerminalKind::ByteLimitReached { domain } => {
            let bound = spec
                .bounds()
                .byte_bounds()
                .iter()
                .find(|bound| bound.domain() == *domain)
                .ok_or(BrowserFinalizationError::ByteDomainLimitMismatch)?;
            CaptureTermination::ByteLimitReached {
                byte_limit: ByteLimit::try_from(bound.limit().get())
                    .map_err(|_| BrowserFinalizationError::ByteDomainLimitMismatch)?,
            }
        }
        BrowserTerminalKind::QuietSettled => {
            CaptureTermination::Settled(settlement.cloned().ok_or(
                BrowserFinalizationError::Invariant("missing settlement evidence"),
            )?)
        }
        BrowserTerminalKind::ControllerCompleted => {
            CaptureTermination::ControllerStopped(ControllerStopReason::GoalSatisfied)
        }
        BrowserTerminalKind::SystemInterrupted { reason } => CaptureTermination::Interrupted(
            InterruptionEvidence::new(InterruptionInitiator::System, reason.clone()),
        ),
        BrowserTerminalKind::CallerCancelled { reason } => CaptureTermination::Interrupted(
            InterruptionEvidence::new(InterruptionInitiator::Caller, reason.clone()),
        ),
        BrowserTerminalKind::ProviderStopped { reason } => {
            CaptureTermination::Interrupted(InterruptionEvidence::new(
                InterruptionInitiator::Provider,
                reason_code(provider_code(*reason))?,
            ))
        }
    })
}

pub(super) fn activity_outcome(
    terminal: &BrowserAdapterTerminal,
    results_complete: bool,
    has_preserved_evidence: bool,
) -> Result<(ActivityOutcome, Option<ActivitySignal>), BrowserFinalizationError> {
    match terminal.kind() {
        BrowserTerminalKind::QuietSettled | BrowserTerminalKind::ControllerCompleted
            if results_complete =>
        {
            Ok((ActivityOutcome::Succeeded, None))
        }
        BrowserTerminalKind::QuietSettled | BrowserTerminalKind::ControllerCompleted => Ok((
            ActivityOutcome::Partial,
            Some(ActivitySignal::new(
                reason_code("browser.capture.incomplete")?,
                RetryDisposition::Unknown,
            )),
        )),
        BrowserTerminalKind::CallerCancelled { reason } => Ok((
            ActivityOutcome::Cancelled,
            Some(ActivitySignal::new(
                reason.clone(),
                RetryDisposition::Unknown,
            )),
        )),
        BrowserTerminalKind::ByteLimitReached { domain } => {
            let code = match domain {
                BrowserByteDomain::CdpDecodedBody => "browser.limit.cdp-decoded-body",
                BrowserByteDomain::DecodedSourceUtf8 => "browser.limit.decoded-source-utf8",
                BrowserByteDomain::RenderedDomUtf8 => "browser.limit.rendered-dom-utf8",
                BrowserByteDomain::AccessibilityJsonUtf8 => "browser.limit.accessibility-json-utf8",
                BrowserByteDomain::ScreenshotPng => "browser.limit.screenshot-png",
                BrowserByteDomain::RuntimeDiagnosticUtf8 => "browser.limit.runtime-diagnostic-utf8",
            };
            Ok((
                ActivityOutcome::Partial,
                Some(ActivitySignal::new(
                    reason_code(code)?,
                    RetryDisposition::NotRetryable,
                )),
            ))
        }
        BrowserTerminalKind::ProviderStopped { reason } => Ok((
            if has_preserved_evidence {
                ActivityOutcome::Partial
            } else {
                ActivityOutcome::Failed
            },
            Some(ActivitySignal::new(
                reason_code(provider_code(*reason))?,
                RetryDisposition::Retryable,
            )),
        )),
        BrowserTerminalKind::DeadlineReached { .. } => Ok((
            ActivityOutcome::Partial,
            Some(ActivitySignal::new(
                reason_code("capture.deadline")?,
                RetryDisposition::NotRetryable,
            )),
        )),
        BrowserTerminalKind::EventLimitReached => Ok((
            ActivityOutcome::Partial,
            Some(ActivitySignal::new(
                reason_code("capture.event-limit")?,
                RetryDisposition::NotRetryable,
            )),
        )),
        BrowserTerminalKind::SystemInterrupted { reason } => Ok((
            ActivityOutcome::Partial,
            Some(ActivitySignal::new(
                reason.clone(),
                RetryDisposition::Retryable,
            )),
        )),
    }
}

pub(super) fn reason_code(value: &str) -> Result<ReasonCode, BrowserFinalizationError> {
    ReasonCode::new(value).map_err(|_| BrowserFinalizationError::Invariant("static reason code"))
}

const fn provider_code(stop: BrowserProviderStop) -> &'static str {
    match stop {
        BrowserProviderStop::PageFailure => "browser.provider.page-failure",
        BrowserProviderStop::RendererFailure => "browser.provider.renderer-failure",
        BrowserProviderStop::BrowserDisconnected => "browser.provider.disconnected",
        BrowserProviderStop::NavigationFailure => "browser.provider.navigation-failure",
        BrowserProviderStop::InternalFailure => "browser.provider.internal-failure",
        BrowserProviderStop::CleanupFailure => "browser.provider.cleanup-failure",
    }
}
