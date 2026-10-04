use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use yosoi_types::ReasonCode;
use yosoi_web_capture::{
    ActivityCount, ByteAccounting, ByteCount, ByteLimit, CaptureDeadline, CaptureDuration,
    CaptureObservation, CaptureObservationError, CaptureOffset, CaptureTermination,
    ControllerStopReason, EventAccounting, EventCount, EventLimit, InFlightActivity,
    InterruptionEvidence, InterruptionInitiator, MeasuredCount, ObservationLimits,
    ObservationPolicy, ObservationWindow, QuietPeriod, QuietPeriodPolicy, SettlementEvidence,
    SettlementPolicy, SettlementPolicyId, TerminalObservationState,
};

#[path = "observation_windows/lifecycle.rs"]
mod lifecycle;
#[path = "observation_windows/limits.rs"]
mod limits;
#[path = "observation_windows/serialization.rs"]
mod serialization;
#[path = "observation_windows/settlement.rs"]
mod settlement;
#[path = "observation_windows/support.rs"]
mod support;
