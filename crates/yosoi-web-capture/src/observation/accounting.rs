//! Explicit admission, retention, loss, and in-flight accounting.

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;
use yosoi_types::ReasonCode;

use super::{ActivityCount, ByteCount, CaptureOffset, EventCount};

/// Compatibility spelling for the canonical measured-value container.
pub type MeasuredCount<T> = yosoi_types::Measured<T, ReasonCode>;

/// Error returned when relevant in-flight activity exceeds total activity.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
#[error("settlement-relevant in-flight activity cannot exceed total in-flight activity")]
pub struct InFlightActivityError;

/// Total and settlement-relevant activity at termination.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct InFlightActivity {
    total: MeasuredCount<ActivityCount>,
    settlement_relevant: MeasuredCount<ActivityCount>,
}

impl InFlightActivity {
    /// Creates in-flight accounting after checking the subset relationship.
    pub fn new(
        total: ActivityCount,
        settlement_relevant: ActivityCount,
    ) -> Result<Self, InFlightActivityError> {
        Self::measured(
            MeasuredCount::Known(total),
            MeasuredCount::Known(settlement_relevant),
        )
    }

    /// Creates accounting from exact producer counts or explicit unavailability.
    pub fn measured(
        total: MeasuredCount<ActivityCount>,
        settlement_relevant: MeasuredCount<ActivityCount>,
    ) -> Result<Self, InFlightActivityError> {
        if let (MeasuredCount::Known(total), MeasuredCount::Known(relevant)) =
            (&total, &settlement_relevant)
            && relevant.get() > total.get()
        {
            return Err(InFlightActivityError);
        }
        Ok(Self {
            total,
            settlement_relevant,
        })
    }

    /// Returns all in-flight activity, preserving whether the producer measured it.
    pub const fn total(&self) -> &MeasuredCount<ActivityCount> {
        &self.total
    }

    /// Returns settlement-relevant activity, preserving whether the producer measured it.
    pub const fn settlement_relevant(&self) -> &MeasuredCount<ActivityCount> {
        &self.settlement_relevant
    }
}

#[derive(Deserialize)]
#[serde(untagged)]
enum InFlightCountWire {
    Known(ActivityCount),
    Measured(MeasuredCount<ActivityCount>),
}
impl InFlightCountWire {
    fn into_measured(self) -> MeasuredCount<ActivityCount> {
        match self {
            Self::Known(value) => MeasuredCount::Known(value),
            Self::Measured(value) => value,
        }
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct InFlightActivityWire {
    total: InFlightCountWire,
    settlement_relevant: InFlightCountWire,
}

impl TryFrom<InFlightActivityWire> for InFlightActivity {
    type Error = InFlightActivityError;

    fn try_from(value: InFlightActivityWire) -> Result<Self, Self::Error> {
        Self::measured(
            value.total.into_measured(),
            value.settlement_relevant.into_measured(),
        )
    }
}

impl Serialize for InFlightActivity {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        use serde::ser::SerializeStruct;
        let mut state = serializer.serialize_struct("InFlightActivity", 2)?;
        if let (MeasuredCount::Known(total), MeasuredCount::Known(relevant)) =
            (&self.total, &self.settlement_relevant)
        {
            state.serialize_field("total", total)?;
            state.serialize_field("settlement_relevant", relevant)?;
        } else {
            state.serialize_field("total", &self.total)?;
            state.serialize_field("settlement_relevant", &self.settlement_relevant)?;
        }
        state.end()
    }
}

impl<'de> Deserialize<'de> for InFlightActivity {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        InFlightActivityWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

/// Error returned when admitted, retained, and dropped event counts disagree.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum EventAccountingError {
    /// More events were retained than admitted.
    #[error("retained events cannot exceed admitted events")]
    RetainedExceedsAdmitted,
    /// Exact dropped-event accounting did not explain the admitted total.
    #[error("retained and known dropped events must equal admitted events")]
    KnownLossMismatch,
    /// Exact event accounting overflowed its integer representation.
    #[error("event accounting exceeds its integer representation")]
    Overflow,
}

/// Admitted, retained, and dropped event counts at termination.
#[derive(Clone, Debug, Eq, Hash, PartialEq, Serialize)]
pub struct EventAccounting {
    admitted: EventCount,
    retained: EventCount,
    dropped: MeasuredCount<EventCount>,
}

impl EventAccounting {
    /// Creates event accounting after checking exact known loss.
    pub fn new(
        admitted: EventCount,
        retained: EventCount,
        dropped: MeasuredCount<EventCount>,
    ) -> Result<Self, EventAccountingError> {
        if retained > admitted {
            return Err(EventAccountingError::RetainedExceedsAdmitted);
        }
        if let MeasuredCount::Known(dropped_count) = &dropped {
            let explained = retained
                .get()
                .checked_add(dropped_count.get())
                .ok_or(EventAccountingError::Overflow)?;
            if explained != admitted.get() {
                return Err(EventAccountingError::KnownLossMismatch);
            }
        }
        Ok(Self {
            admitted,
            retained,
            dropped,
        })
    }

    /// Returns events admitted by the observation coordinator.
    pub const fn admitted(&self) -> EventCount {
        self.admitted
    }

    /// Returns admitted events retained in the capture.
    pub const fn retained(&self) -> EventCount {
        self.retained
    }

    /// Returns exact or explicitly unavailable loss after admission.
    pub const fn dropped(&self) -> &MeasuredCount<EventCount> {
        &self.dropped
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct EventAccountingWire {
    admitted: EventCount,
    retained: EventCount,
    dropped: MeasuredCount<EventCount>,
}

impl TryFrom<EventAccountingWire> for EventAccounting {
    type Error = EventAccountingError;

    fn try_from(value: EventAccountingWire) -> Result<Self, Self::Error> {
        Self::new(value.admitted, value.retained, value.dropped)
    }
}

impl<'de> Deserialize<'de> for EventAccounting {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        EventAccountingWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

/// Error returned when admitted, retained, and dropped byte counts disagree.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum ByteAccountingError {
    /// More bytes were retained than admitted.
    #[error("retained bytes cannot exceed admitted bytes")]
    RetainedExceedsAdmitted,
    /// Exact dropped-byte accounting did not explain the admitted total.
    #[error("retained and known dropped bytes must equal admitted bytes")]
    KnownLossMismatch,
    /// Exact byte accounting overflowed its integer representation.
    #[error("byte accounting exceeds its integer representation")]
    Overflow,
}

/// Admitted, retained, and dropped byte counts at termination.
#[derive(Clone, Debug, Eq, Hash, PartialEq, Serialize)]
pub struct ByteAccounting {
    admitted: ByteCount,
    retained: ByteCount,
    dropped: MeasuredCount<ByteCount>,
}

impl ByteAccounting {
    /// Creates byte accounting after checking exact known loss.
    pub fn new(
        admitted: ByteCount,
        retained: ByteCount,
        dropped: MeasuredCount<ByteCount>,
    ) -> Result<Self, ByteAccountingError> {
        if retained > admitted {
            return Err(ByteAccountingError::RetainedExceedsAdmitted);
        }
        if let MeasuredCount::Known(dropped_count) = &dropped {
            let explained = retained
                .get()
                .checked_add(dropped_count.get())
                .ok_or(ByteAccountingError::Overflow)?;
            if explained != admitted.get() {
                return Err(ByteAccountingError::KnownLossMismatch);
            }
        }
        Ok(Self {
            admitted,
            retained,
            dropped,
        })
    }

    /// Returns bytes admitted by the observation coordinator.
    pub const fn admitted(&self) -> ByteCount {
        self.admitted
    }

    /// Returns admitted bytes retained in the capture.
    pub const fn retained(&self) -> ByteCount {
        self.retained
    }

    /// Returns exact or explicitly unavailable loss after admission.
    pub const fn dropped(&self) -> &MeasuredCount<ByteCount> {
        &self.dropped
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ByteAccountingWire {
    admitted: ByteCount,
    retained: ByteCount,
    dropped: MeasuredCount<ByteCount>,
}

impl TryFrom<ByteAccountingWire> for ByteAccounting {
    type Error = ByteAccountingError;

    fn try_from(value: ByteAccountingWire) -> Result<Self, Self::Error> {
        Self::new(value.admitted, value.retained, value.dropped)
    }
}

impl<'de> Deserialize<'de> for ByteAccounting {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        ByteAccountingWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

/// Retained data, loss measurements, and unfinished activity at termination.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TerminalObservationState {
    observed_through: CaptureOffset,
    events: EventAccounting,
    bytes: ByteAccounting,
    in_flight: InFlightActivity,
}

impl TerminalObservationState {
    /// Creates terminal accounting at one relative observation offset.
    pub const fn new(
        observed_through: CaptureOffset,
        events: EventAccounting,
        bytes: ByteAccounting,
        in_flight: InFlightActivity,
    ) -> Self {
        Self {
            observed_through,
            events,
            bytes,
            in_flight,
        }
    }

    /// Returns the relative offset covered by terminal accounting.
    pub const fn observed_through(&self) -> CaptureOffset {
        self.observed_through
    }

    /// Returns admitted, retained, and dropped event accounting.
    pub const fn events(&self) -> &EventAccounting {
        &self.events
    }

    /// Returns admitted, retained, and dropped byte accounting.
    pub const fn bytes(&self) -> &ByteAccounting {
        &self.bytes
    }

    /// Returns activity still in flight at termination.
    pub fn in_flight(&self) -> InFlightActivity {
        self.in_flight.clone()
    }
}
