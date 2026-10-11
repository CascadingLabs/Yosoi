#![allow(clippy::missing_const_for_fn)]
use crate::internal::types::ReasonCode;
use crate::internal::web_capture::browser_spec::BrowserByteDomain;
use crate::internal::web_capture::{CaptureDeadline, CaptureOffset};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BrowserProviderStop {
    PageFailure,
    RendererFailure,
    BrowserDisconnected,
    NavigationFailure,
    InternalFailure,
    CleanupFailure,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BrowserTerminalKind {
    DeadlineReached { at: CaptureOffset },
    SystemInterrupted { reason: ReasonCode },
    CallerCancelled { reason: ReasonCode },
    ProviderStopped { reason: BrowserProviderStop },
    EventLimitReached,
    ByteLimitReached { domain: BrowserByteDomain },
    QuietSettled,
    ControllerCompleted,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BrowserTerminalSignal {
    DeadlineReached,
    SystemInterrupted { reason: ReasonCode },
    CallerInterrupted { reason: ReasonCode },
    CleanupFailed,
    ProviderFailed { reason: BrowserProviderStop },
    EventLimitReached,
    ByteLimitReached { domain: BrowserByteDomain },
    QuietSettled,
    ControllerCompleted,
    NavigationCompleted,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserTerminalCandidate {
    offset: CaptureOffset,
    signal: BrowserTerminalSignal,
}
impl BrowserTerminalCandidate {
    pub const fn new(offset: CaptureOffset, signal: BrowserTerminalSignal) -> Self {
        Self { offset, signal }
    }
    pub const fn offset(&self) -> CaptureOffset {
        self.offset
    }
    pub const fn signal(&self) -> &BrowserTerminalSignal {
        &self.signal
    }
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserAdapterTerminal {
    at: CaptureOffset,
    kind: BrowserTerminalKind,
}
impl BrowserAdapterTerminal {
    pub const fn at(&self) -> CaptureOffset {
        self.at
    }
    pub const fn kind(&self) -> &BrowserTerminalKind {
        &self.kind
    }
}
pub fn resolve_browser_terminal(
    candidates: &[BrowserTerminalCandidate],
    maximum: CaptureDeadline,
) -> Option<BrowserAdapterTerminal> {
    let deadline = CaptureOffset::from_microseconds(maximum.as_microseconds());
    let normalized_offset = |candidate: &BrowserTerminalCandidate| {
        if matches!(candidate.signal, BrowserTerminalSignal::DeadlineReached)
            || candidate.offset >= deadline
        {
            deadline
        } else {
            candidate.offset
        }
    };
    let earliest = candidates
        .iter()
        .filter(|c| !matches!(c.signal, BrowserTerminalSignal::NavigationCompleted))
        .map(normalized_offset)
        .min()?;
    if earliest == deadline {
        return Some(BrowserAdapterTerminal {
            at: earliest,
            kind: BrowserTerminalKind::DeadlineReached { at: earliest },
        });
    }
    for priority in 0_u8..8 {
        for c in candidates
            .iter()
            .filter(|c| normalized_offset(c) == earliest)
        {
            let result = match (priority, &c.signal) {
                (0, BrowserTerminalSignal::SystemInterrupted { reason }) => {
                    Some(BrowserTerminalKind::SystemInterrupted {
                        reason: reason.clone(),
                    })
                }
                (1, BrowserTerminalSignal::CallerInterrupted { reason }) => {
                    Some(BrowserTerminalKind::CallerCancelled {
                        reason: reason.clone(),
                    })
                }
                (2, BrowserTerminalSignal::CleanupFailed) => {
                    Some(BrowserTerminalKind::ProviderStopped {
                        reason: BrowserProviderStop::CleanupFailure,
                    })
                }
                (3, BrowserTerminalSignal::ProviderFailed { reason }) => {
                    Some(BrowserTerminalKind::ProviderStopped { reason: *reason })
                }
                (4, BrowserTerminalSignal::EventLimitReached) => {
                    Some(BrowserTerminalKind::EventLimitReached)
                }
                (5, BrowserTerminalSignal::ByteLimitReached { domain }) => {
                    Some(BrowserTerminalKind::ByteLimitReached { domain: *domain })
                }
                (6, BrowserTerminalSignal::QuietSettled) => Some(BrowserTerminalKind::QuietSettled),
                (7, BrowserTerminalSignal::ControllerCompleted) => {
                    Some(BrowserTerminalKind::ControllerCompleted)
                }
                _ => None,
            };
            if result.is_some() {
                return result.map(|kind| BrowserAdapterTerminal { at: earliest, kind });
            }
        }
    }
    None
}
