use crate::internal::types::{ArtifactRef, Producer, Schema};
use crate::internal::web_capture::{DecodedSourceArtifactRef, SourceArtifactRef};
use chrono::{DateTime, Utc};
use thiserror::Error;
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum DecodedOutputIdentityError {
    #[error("decoded output must belong to the source activity")]
    DifferentActivity,
    #[error("decoded output must have an artifact ID distinct from its source")]
    SameArtifact,
    #[error("decoded output must derive directly and only from its source")]
    InvalidLineage,
}

/// Caller-owned durable identity for the decoded artifact.
#[derive(Clone, Debug)]
pub struct DecodedOutputIdentity {
    reference: DecodedSourceArtifactRef,
    producer: Producer,
    schema: Schema,
    derived_from: Vec<ArtifactRef>,
    generated_at: Option<DateTime<Utc>>,
}
impl DecodedOutputIdentity {
    pub fn new(
        reference: DecodedSourceArtifactRef,
        producer: Producer,
        schema: Schema,
        derived_from: Vec<ArtifactRef>,
        source: SourceArtifactRef,
    ) -> Result<Self, DecodedOutputIdentityError> {
        let output = reference.as_untyped();
        let input = source.as_untyped();
        if output.activity_id() != input.activity_id() {
            return Err(DecodedOutputIdentityError::DifferentActivity);
        }
        if output.artifact_id() == input.artifact_id() {
            return Err(DecodedOutputIdentityError::SameArtifact);
        }
        if derived_from.as_slice() != [input] {
            return Err(DecodedOutputIdentityError::InvalidLineage);
        }
        Ok(Self {
            reference,
            producer,
            schema,
            derived_from,
            generated_at: None,
        })
    }
    pub const fn with_generated_at(mut self, generated_at: DateTime<Utc>) -> Self {
        self.generated_at = Some(generated_at);
        self
    }
    pub const fn generated_at(&self) -> Option<&DateTime<Utc>> {
        self.generated_at.as_ref()
    }
    pub const fn reference(&self) -> DecodedSourceArtifactRef {
        self.reference
    }
    pub const fn producer(&self) -> &Producer {
        &self.producer
    }
    pub const fn schema(&self) -> &Schema {
        &self.schema
    }
    pub fn derived_from(&self) -> &[ArtifactRef] {
        &self.derived_from
    }
}
