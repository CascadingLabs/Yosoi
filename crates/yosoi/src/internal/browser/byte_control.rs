//! Browser-native byte limits and accounting.
//!
//! These types describe bytes observed and retained by VoidCrawl in concrete
//! browser/CDP domains. They deliberately do not model durable artifacts or
//! import Yosoi capture types.

use crate::internal::types as yosoi_types;

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;
mod wire_scope;
use crate::internal::types::{ByteCount, ByteCountOverflow, ByteLimit, ByteLimitError};
pub use wire_scope::{BrowserBudgetScope, BrowserLimitScope};

/// Why exact byte loss or extent is unavailable.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserByteMeasurementUnavailableReason {
    ProviderDidNotReport,
    CaptureEndedEarly,
    NotApplicable,
}

/// A byte count or an explicit provider reason it cannot be known.
pub type MeasuredBrowserBytes =
    yosoi_types::FlatMeasured<ByteCount, BrowserByteMeasurementUnavailableReason>;

/// Concrete browser/CDP representation in which bytes are counted.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserByteDomain {
    CdpDecodedBody,
    RenderedDomUtf8,
    AccessibilityJsonUtf8,
    RuntimeDiagnosticUtf8,
    ScreenshotPng,
    RecordingFrame,
    EncodedRecording,
}

/// One configured browser byte budget.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserByteSpec {
    domain: BrowserByteDomain,
    limit: ByteLimit,
    limit_scope: BrowserLimitScope,
    budget_scope: BrowserBudgetScope,
}

impl BrowserByteSpec {
    #[must_use]
    pub const fn new(
        domain: BrowserByteDomain,
        limit: ByteLimit,
        limit_scope: BrowserLimitScope,
        budget_scope: BrowserBudgetScope,
    ) -> Self {
        Self {
            domain,
            limit,
            limit_scope,
            budget_scope,
        }
    }

    #[must_use]
    pub const fn domain(self) -> BrowserByteDomain {
        self.domain
    }

    #[must_use]
    pub const fn limit(self) -> ByteLimit {
        self.limit
    }

    #[must_use]
    pub const fn limit_scope(self) -> BrowserLimitScope {
        self.limit_scope
    }

    #[must_use]
    pub const fn budget_scope(self) -> BrowserBudgetScope {
        self.budget_scope
    }
}

/// Contradiction or overflow in browser byte accounting.
#[derive(Debug, Clone, Copy, Error, PartialEq, Eq)]
pub enum BrowserByteAccountingError {
    #[error("retained bytes cannot exceed observed bytes")]
    RetainedExceedsObserved,
    #[error("retained and known discarded bytes must equal observed bytes")]
    KnownDiscardMismatch,
    #[error("browser byte accounting overflowed")]
    Overflow,
    #[error("browser byte specification domain does not match the reported payload")]
    SpecDomainMismatch,
    #[error("retained bytes exceed the configured browser byte limit")]
    RetainedExceedsLimit,
}

/// Bytes delivered to VoidCrawl, retained, and discarded after observation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct BrowserByteAccounting {
    observed: ByteCount,
    retained: ByteCount,
    discarded: MeasuredBrowserBytes,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserByteAccountingWire {
    observed: ByteCount,
    retained: ByteCount,
    discarded: MeasuredBrowserBytes,
}

impl TryFrom<BrowserByteAccountingWire> for BrowserByteAccounting {
    type Error = BrowserByteAccountingError;

    fn try_from(value: BrowserByteAccountingWire) -> Result<Self, Self::Error> {
        Self::new(value.observed, value.retained, value.discarded)
    }
}

impl<'de> Deserialize<'de> for BrowserByteAccounting {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        BrowserByteAccountingWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

impl BrowserByteAccounting {
    pub fn new(
        observed: ByteCount,
        retained: ByteCount,
        discarded: MeasuredBrowserBytes,
    ) -> Result<Self, BrowserByteAccountingError> {
        if retained > observed {
            return Err(BrowserByteAccountingError::RetainedExceedsObserved);
        }
        if let MeasuredBrowserBytes::Known { value: discarded } = discarded {
            let explained = retained
                .get()
                .checked_add(discarded.get())
                .ok_or(BrowserByteAccountingError::Overflow)?;
            if explained != observed.get() {
                return Err(BrowserByteAccountingError::KnownDiscardMismatch);
            }
        }
        Ok(Self {
            observed,
            retained,
            discarded,
        })
    }

    #[must_use]
    pub const fn observed(self) -> ByteCount {
        self.observed
    }

    #[must_use]
    pub const fn retained(self) -> ByteCount {
        self.retained
    }

    #[must_use]
    pub const fn discarded(self) -> MeasuredBrowserBytes {
        self.discarded
    }
}

/// Failure to construct a canonical browser byte report.
#[derive(Debug, Clone, Copy, Error, PartialEq, Eq)]
pub enum BrowserByteReportError {
    #[error(transparent)]
    Limit(#[from] ByteLimitError),
    #[error(transparent)]
    Accounting(#[from] BrowserByteAccountingError),
    #[error("browser byte report extent contradicts its accounting")]
    ExtentMismatch,
}

impl From<ByteCountOverflow> for BrowserByteReportError {
    fn from(_: ByteCountOverflow) -> Self {
        Self::Limit(ByteLimitError::TooLarge)
    }
}

/// Terminal extent of one browser payload.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum BrowserPayloadExtent {
    Complete,
    Truncated {
        complete_bytes: MeasuredBrowserBytes,
    },
    Discarded {
        observed_bytes: MeasuredBrowserBytes,
    },
    Unavailable {
        reason: BrowserPayloadUnavailableReason,
    },
    Failed {
        reason: BrowserPayloadFailureReason,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserPayloadUnavailableReason {
    ProviderDidNotReport,
    NotCollected,
    Unsupported,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserPayloadFailureReason {
    ProviderRejected,
    ProviderDisconnected,
    InvalidEncoding,
    Deadline,
    Cancelled,
    SinkFailure,
}

/// Canonical byte facts for one browser payload or aggregate collector.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct BrowserByteReport {
    domain: BrowserByteDomain,
    spec: Option<BrowserByteSpec>,
    accounting: BrowserByteAccounting,
    extent: BrowserPayloadExtent,
    additional_loss: MeasuredBrowserBytes,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserByteReportWire {
    domain: BrowserByteDomain,
    spec: Option<BrowserByteSpec>,
    accounting: BrowserByteAccounting,
    extent: BrowserPayloadExtent,
    additional_loss: MeasuredBrowserBytes,
}

impl<'de> Deserialize<'de> for BrowserByteReport {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let wire = BrowserByteReportWire::deserialize(deserializer)?;
        Self::new(
            wire.domain,
            wire.spec,
            wire.accounting,
            wire.extent,
            wire.additional_loss,
        )
        .map_err(D::Error::custom)
    }
}

impl BrowserByteReport {
    pub fn new(
        domain: BrowserByteDomain,
        spec: Option<BrowserByteSpec>,
        accounting: BrowserByteAccounting,
        extent: BrowserPayloadExtent,
        additional_loss: MeasuredBrowserBytes,
    ) -> Result<Self, BrowserByteReportError> {
        if spec.is_some_and(|spec| spec.domain() != domain) {
            return Err(BrowserByteAccountingError::SpecDomainMismatch.into());
        }
        if spec.is_some_and(|spec| accounting.retained().get() > spec.limit().get()) {
            return Err(BrowserByteAccountingError::RetainedExceedsLimit.into());
        }
        let discarded_is_zero = matches!(
            accounting.discarded(),
            MeasuredBrowserBytes::Known { value } if value.get() == 0
        );
        let additional_loss_is_zero = matches!(
            additional_loss,
            MeasuredBrowserBytes::Known { value } if value.get() == 0
        );
        match extent {
            BrowserPayloadExtent::Complete if !discarded_is_zero || !additional_loss_is_zero => {
                return Err(BrowserByteReportError::ExtentMismatch);
            }
            BrowserPayloadExtent::Truncated { complete_bytes } => {
                if discarded_is_zero && additional_loss_is_zero {
                    return Err(BrowserByteReportError::ExtentMismatch);
                }
                if let MeasuredBrowserBytes::Known { value: complete } = complete_bytes {
                    if complete < accounting.observed() {
                        return Err(BrowserByteReportError::ExtentMismatch);
                    }
                    if let MeasuredBrowserBytes::Known { value: additional } = additional_loss {
                        let expected = accounting
                            .observed()
                            .get()
                            .checked_add(additional.get())
                            .ok_or(BrowserByteAccountingError::Overflow)?;
                        if complete.get() != expected {
                            return Err(BrowserByteReportError::ExtentMismatch);
                        }
                    }
                }
            }
            BrowserPayloadExtent::Discarded { observed_bytes }
                if accounting.retained().get() != 0 || observed_bytes != accounting.discarded() =>
            {
                return Err(BrowserByteReportError::ExtentMismatch);
            }
            BrowserPayloadExtent::Unavailable { .. }
                if accounting.observed().get() != 0 || accounting.retained().get() != 0 =>
            {
                return Err(BrowserByteReportError::ExtentMismatch);
            }
            _ => {}
        }
        Ok(Self {
            domain,
            spec,
            accounting,
            extent,
            additional_loss,
        })
    }
    pub fn from_known_extent(
        domain: BrowserByteDomain,
        spec: Option<BrowserByteSpec>,
        observed: ByteCount,
        retained: ByteCount,
    ) -> Result<Self, BrowserByteReportError> {
        if spec.is_some_and(|spec| spec.domain() != domain) {
            return Err(BrowserByteAccountingError::SpecDomainMismatch.into());
        }
        let discarded = observed
            .get()
            .checked_sub(retained.get())
            .ok_or(BrowserByteAccountingError::RetainedExceedsObserved)?;
        let accounting = BrowserByteAccounting::new(
            observed,
            retained,
            MeasuredBrowserBytes::Known {
                value: ByteCount::new(discarded),
            },
        )?;
        let extent = if discarded == 0 {
            BrowserPayloadExtent::Complete
        } else {
            BrowserPayloadExtent::Truncated {
                complete_bytes: MeasuredBrowserBytes::Known { value: observed },
            }
        };
        Self::new(
            domain,
            spec,
            accounting,
            extent,
            MeasuredBrowserBytes::Known {
                value: ByteCount::new(0),
            },
        )
    }

    /// Reports a payload deliberately discarded without retaining its bytes.
    pub fn discarded(
        domain: BrowserByteDomain,
        spec: Option<BrowserByteSpec>,
        observed_bytes: MeasuredBrowserBytes,
    ) -> Result<Self, BrowserByteReportError> {
        let observed = match observed_bytes {
            MeasuredBrowserBytes::Known { value } => value,
            MeasuredBrowserBytes::Unavailable { .. } => ByteCount::new(0),
        };
        let accounting = BrowserByteAccounting::new(observed, ByteCount::new(0), observed_bytes)?;
        Self::new(
            domain,
            spec,
            accounting,
            BrowserPayloadExtent::Discarded { observed_bytes },
            MeasuredBrowserBytes::Known {
                value: ByteCount::new(0),
            },
        )
    }

    /// Reports a truncated payload, including loss before it was observed
    /// locally.
    pub fn truncated(
        domain: BrowserByteDomain,
        spec: Option<BrowserByteSpec>,
        accounting: BrowserByteAccounting,
        complete_bytes: MeasuredBrowserBytes,
        additional_loss: MeasuredBrowserBytes,
    ) -> Result<Self, BrowserByteReportError> {
        Self::new(
            domain,
            spec,
            accounting,
            BrowserPayloadExtent::Truncated { complete_bytes },
            additional_loss,
        )
    }

    /// Reports a failed payload without presenting it as a complete capture.
    pub fn failed(
        domain: BrowserByteDomain,
        spec: Option<BrowserByteSpec>,
        reason: BrowserPayloadFailureReason,
    ) -> Result<Self, BrowserByteReportError> {
        let zero = ByteCount::new(0);
        let unavailable = MeasuredBrowserBytes::Unavailable {
            reason: BrowserByteMeasurementUnavailableReason::CaptureEndedEarly,
        };
        let accounting = BrowserByteAccounting::new(zero, zero, unavailable)?;
        Self::failed_with_accounting(domain, spec, accounting, reason, unavailable)
    }

    /// Reports a failed payload while preserving any valid partial accounting.
    pub fn failed_with_accounting(
        domain: BrowserByteDomain,
        spec: Option<BrowserByteSpec>,
        accounting: BrowserByteAccounting,
        reason: BrowserPayloadFailureReason,
        additional_loss: MeasuredBrowserBytes,
    ) -> Result<Self, BrowserByteReportError> {
        Self::new(
            domain,
            spec,
            accounting,
            BrowserPayloadExtent::Failed { reason },
            additional_loss,
        )
    }

    pub const fn unavailable(
        domain: BrowserByteDomain,
        reason: BrowserPayloadUnavailableReason,
    ) -> Self {
        let zero = ByteCount::new(0);
        Self {
            domain,
            spec: None,
            accounting: BrowserByteAccounting {
                observed: zero,
                retained: zero,
                discarded: MeasuredBrowserBytes::Unavailable {
                    reason: BrowserByteMeasurementUnavailableReason::NotApplicable,
                },
            },
            extent: BrowserPayloadExtent::Unavailable { reason },
            additional_loss: MeasuredBrowserBytes::Unavailable {
                reason: BrowserByteMeasurementUnavailableReason::ProviderDidNotReport,
            },
        }
    }

    /// Reports an unavailable payload while retaining a requested collection
    /// spec.
    pub fn unavailable_with_spec(
        domain: BrowserByteDomain,
        spec: Option<BrowserByteSpec>,
        reason: BrowserPayloadUnavailableReason,
    ) -> Result<Self, BrowserByteReportError> {
        let zero = ByteCount::new(0);
        let accounting = BrowserByteAccounting::new(
            zero,
            zero,
            MeasuredBrowserBytes::Unavailable {
                reason: BrowserByteMeasurementUnavailableReason::NotApplicable,
            },
        )?;
        Self::new(
            domain,
            spec,
            accounting,
            BrowserPayloadExtent::Unavailable { reason },
            MeasuredBrowserBytes::Unavailable {
                reason: BrowserByteMeasurementUnavailableReason::ProviderDidNotReport,
            },
        )
    }

    #[must_use]
    pub const fn domain(self) -> BrowserByteDomain {
        self.domain
    }
    #[must_use]
    pub const fn spec(self) -> Option<BrowserByteSpec> {
        self.spec
    }
    #[must_use]
    pub const fn accounting(self) -> BrowserByteAccounting {
        self.accounting
    }
    #[must_use]
    pub const fn extent(self) -> BrowserPayloadExtent {
        self.extent
    }
    #[must_use]
    pub const fn additional_loss(self) -> MeasuredBrowserBytes {
        self.additional_loss
    }
}

/// Admission decision for one observed byte chunk.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BrowserByteAdmission {
    pub observed: ByteCount,
    pub retain_prefix: ByteCount,
    pub discarded: ByteCount,
    pub limit_exceeded: bool,
}

/// Checked incremental budget used by streaming collectors and bounded sinks.
#[derive(Debug, Clone, Copy)]
pub struct BrowserByteBudget {
    spec: BrowserByteSpec,
    observed: u64,
    retained: u64,
    discarded: u64,
}

impl BrowserByteBudget {
    #[must_use]
    pub const fn new(spec: BrowserByteSpec) -> Self {
        Self {
            spec,
            observed: 0,
            retained: 0,
            discarded: 0,
        }
    }

    pub fn observe_chunk(
        &mut self,
        bytes: ByteCount,
    ) -> Result<BrowserByteAdmission, BrowserByteAccountingError> {
        self.observed = self
            .observed
            .checked_add(bytes.get())
            .ok_or(BrowserByteAccountingError::Overflow)?;
        let remaining = self.spec.limit().get().saturating_sub(self.retained);
        let retain_prefix = remaining.min(bytes.get());
        let discarded = bytes
            .get()
            .checked_sub(retain_prefix)
            .ok_or(BrowserByteAccountingError::Overflow)?;
        self.retained = self
            .retained
            .checked_add(retain_prefix)
            .ok_or(BrowserByteAccountingError::Overflow)?;
        self.discarded = self
            .discarded
            .checked_add(discarded)
            .ok_or(BrowserByteAccountingError::Overflow)?;
        Ok(BrowserByteAdmission {
            observed: bytes,
            retain_prefix: ByteCount::new(retain_prefix),
            discarded: ByteCount::new(discarded),
            limit_exceeded: discarded != 0,
        })
    }

    pub fn accounting(self) -> Result<BrowserByteAccounting, BrowserByteAccountingError> {
        BrowserByteAccounting::new(
            ByteCount::new(self.observed),
            ByteCount::new(self.retained),
            MeasuredBrowserBytes::Known {
                value: ByteCount::new(self.discarded),
            },
        )
    }

    #[must_use]
    pub const fn spec(self) -> BrowserByteSpec {
        self.spec
    }
}
