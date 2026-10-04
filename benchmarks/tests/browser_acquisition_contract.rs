//! Browser-side characterization at the shared acquisition boundary.

#![allow(clippy::panic, reason = "characterization fixtures fail loudly")]

use yosoi_types::ReasonCode;
use yosoi_web_capture::{
    AcquiredPayloadOutcome, ArtifactStagingOutcome, BrowserArtifactMapping, BrowserByteLayer,
    BrowserProviderStop, BrowserStagingFamily, BrowserTerminalCandidate, BrowserTerminalKind,
    BrowserTerminalSignal, ByteCount, CaptureDeadline, CaptureOffset, LossExtent, MeasuredCount,
    StagingState, WebArtifactFamily, resolve_browser_terminal,
};

fn reason(name: &'static str) -> ReasonCode {
    ReasonCode::new(name).unwrap_or_else(|error| panic!("reason {name}: {error}"))
}

fn source_mapping() -> BrowserArtifactMapping {
    BrowserArtifactMapping::new(
        BrowserStagingFamily::Artifact(WebArtifactFamily::Source),
        BrowserByteLayer::DecodedResponseBody,
    )
    .unwrap_or_else(|error| panic!("source mapping: {error}"))
}

#[test]
fn canonical_payload_states_keep_their_meaning_in_browser_staging() {
    let cases = [
        (
            AcquiredPayloadOutcome::complete(b"complete".to_vec()),
            StagingState::Complete,
            Some(b"complete".as_slice()),
            8,
            LossExtent::Known(0),
        ),
        (
            AcquiredPayloadOutcome::truncated(
                b"part".to_vec(),
                ByteCount::new(9),
                MeasuredCount::Known(ByteCount::new(5)),
                reason("characterization.browser.truncated"),
            ),
            StagingState::Truncated,
            Some(b"part".as_slice()),
            9,
            LossExtent::Known(5),
        ),
        (
            AcquiredPayloadOutcome::discarded(
                MeasuredCount::Unavailable {
                    reason: reason("characterization.browser.unknown-size"),
                },
                reason("characterization.browser.discarded"),
            ),
            StagingState::Discarded,
            None,
            0,
            LossExtent::Unknown,
        ),
        (
            AcquiredPayloadOutcome::unavailable(reason("characterization.browser.unavailable")),
            StagingState::Unavailable,
            None,
            0,
            LossExtent::Known(0),
        ),
        (
            AcquiredPayloadOutcome::failed(reason("characterization.browser.failed")),
            StagingState::Failed,
            None,
            0,
            LossExtent::Known(0),
        ),
    ];

    for (outcome, expected_state, expected_bytes, expected_observed, expected_loss) in cases {
        let outcome = outcome.unwrap_or_else(|error| panic!("canonical payload: {error}"));
        let staged = ArtifactStagingOutcome::acquired_payload(source_mapping(), outcome)
            .unwrap_or_else(|error| panic!("browser staging: {error}"));
        assert_eq!(staged.state(), expected_state);
        assert_eq!(staged.bytes(), expected_bytes);
        let accounting = staged
            .accounting()
            .unwrap_or_else(|error| panic!("browser accounting: {error}"));
        assert_eq!(accounting.observed(), expected_observed);
        assert_eq!(accounting.lost(), expected_loss);
    }
}

#[test]
fn simultaneous_browser_terminal_precedence_is_closed_and_stable() {
    let offset = CaptureOffset::from_microseconds(10);
    let maximum =
        CaptureDeadline::try_from(100).unwrap_or_else(|error| panic!("maximum elapsed: {error}"));
    let system_reason = reason("characterization.browser.system");
    let caller_reason = reason("characterization.browser.caller");
    let ordered = [
        BrowserTerminalSignal::SystemInterrupted {
            reason: system_reason.clone(),
        },
        BrowserTerminalSignal::CallerInterrupted {
            reason: caller_reason.clone(),
        },
        BrowserTerminalSignal::CleanupFailed,
        BrowserTerminalSignal::ProviderFailed {
            reason: BrowserProviderStop::BrowserDisconnected,
        },
        BrowserTerminalSignal::EventLimitReached,
        BrowserTerminalSignal::ByteLimitReached {
            domain: yosoi_web_capture::BrowserByteDomain::CdpDecodedBody,
        },
        BrowserTerminalSignal::QuietSettled,
        BrowserTerminalSignal::ControllerCompleted,
    ];
    let expected = [
        BrowserTerminalKind::SystemInterrupted {
            reason: system_reason,
        },
        BrowserTerminalKind::CallerCancelled {
            reason: caller_reason,
        },
        BrowserTerminalKind::ProviderStopped {
            reason: BrowserProviderStop::CleanupFailure,
        },
        BrowserTerminalKind::ProviderStopped {
            reason: BrowserProviderStop::BrowserDisconnected,
        },
        BrowserTerminalKind::EventLimitReached,
        BrowserTerminalKind::ByteLimitReached {
            domain: yosoi_web_capture::BrowserByteDomain::CdpDecodedBody,
        },
        BrowserTerminalKind::QuietSettled,
        BrowserTerminalKind::ControllerCompleted,
    ];

    for start in 0..ordered.len() {
        let candidates = ordered[start..]
            .iter()
            .cloned()
            .map(|signal| BrowserTerminalCandidate::new(offset, signal))
            .collect::<Vec<_>>();
        let terminal = resolve_browser_terminal(&candidates, maximum)
            .unwrap_or_else(|| panic!("terminal case {start}"));
        assert_eq!(terminal.kind(), &expected[start]);
    }

    let deadline = CaptureOffset::from_microseconds(100);
    let deadline_tie = [
        BrowserTerminalCandidate::new(deadline, BrowserTerminalSignal::ControllerCompleted),
        BrowserTerminalCandidate::new(deadline, BrowserTerminalSignal::CleanupFailed),
    ];
    assert_eq!(
        resolve_browser_terminal(&deadline_tie, maximum).map(|value| value.kind().clone()),
        Some(BrowserTerminalKind::DeadlineReached { at: deadline })
    );
}
