//! Shared activity, evidence, and wire vocabulary for Yosoi-compatible systems.
//!
//! This crate is not limited to code hosted in Yosoi repositories. Independent
//! producers such as VoidCrawl can use the same dependency-light types to emit
//! evidence that Yosoi and other consumers understand. Its public values
//! describe data; they do not capture pages, drive providers, persist data, or
//! bind the vocabulary to an SDK.
//!
//! # Invariants
//!
//! - Dependencies point only toward similarly foundational, dependency-light
//!   libraries.
//! - Capture implementations and other runtime concerns depend on this crate,
//!   never the reverse.
//! - A type belongs here only when a current cross-component or wire-format use
//!   requires it.

mod activity;
mod artifact;
mod browser;
mod digest;
mod identity;
mod provenance;
mod quantities;
mod vocabulary;

pub use activity::{
    ActivityOutcome, ActivityReceipt, ActivityReceiptError, ActivitySignal, CaptureReceipt,
    CaptureReceiptError, RetryDisposition,
};
pub use artifact::{ArtifactAvailability, ArtifactRecord, ArtifactRecordError};
pub use browser::{
    BrowserAccessibilityCaptureMode, BrowserAccessibilityIgnoredNodes, BrowserAccessibilitySchema,
    BrowserDocumentEpoch, BrowserFailureReason, BrowserFrameId, BrowserMode, BrowserResourceId,
    BrowserResourceOutcome, ColorScheme, EnvironmentValue, ReducedMotion, Viewport, ViewportError,
};
pub use digest::{Sha256Digest, Sha256DigestParseError};
pub use identity::{
    ActivityId, ArtifactId, ArtifactIdError, ArtifactRef, CaptureArtifactRef, CaptureId,
    OccurrenceIdParseError,
};
pub use provenance::Provenance;
pub use quantities::{
    BudgetScope, ByteCount, ByteCountOverflow, ByteLimit, ByteLimitError, CaptureDeadline,
    CaptureDeadlineError, CaptureDuration, CaptureOffset, EventCount, FlatMeasured,
    LimitEnforcement, LossExtent, Measured,
};
pub use vocabulary::{
    NamespacedIdError, OperationId, Producer, ProducerId, ProducerVersion, ProducerVersionError,
    ReasonCode, Schema, SchemaId, SchemaVersion, SchemaVersionError,
};

#[cfg(test)]
mod integration_tests;
