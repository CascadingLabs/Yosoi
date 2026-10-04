//! Immediate production provenance for one value or artifact.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

use crate::{ActivityId, ArtifactRef, Producer, Schema};

/// Immediate, explicit production provenance for one value or artifact.
///
/// No field is inferred from package metadata, environment variables, a global
/// clock, or process-global configuration. Callers must supply the occurrence,
/// producer, schema, timestamp, and direct inputs explicitly.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Provenance {
    activity_id: ActivityId,
    producer: Producer,
    schema: Schema,
    generated_at: DateTime<Utc>,
    derived_from: Vec<ArtifactRef>,
}

impl Provenance {
    /// Creates immediate provenance from entirely explicit caller-owned values.
    pub const fn new(
        activity_id: ActivityId,
        producer: Producer,
        schema: Schema,
        generated_at: DateTime<Utc>,
        derived_from: Vec<ArtifactRef>,
    ) -> Self {
        Self {
            activity_id,
            producer,
            schema,
            generated_at,
            derived_from,
        }
    }

    /// Returns the occurrence that generated the value.
    pub const fn activity_id(&self) -> ActivityId {
        self.activity_id
    }

    /// Returns the component that generated the value.
    pub const fn producer(&self) -> &Producer {
        &self.producer
    }

    /// Returns the representation used by the value.
    pub const fn schema(&self) -> &Schema {
        &self.schema
    }

    /// Returns the explicit production timestamp.
    pub const fn generated_at(&self) -> &DateTime<Utc> {
        &self.generated_at
    }

    /// Returns direct input artifacts used to produce the value.
    ///
    /// These references record lineage only. They do not determine the output
    /// artifact's location identity or imply byte-for-byte equivalence.
    pub fn derived_from(&self) -> &[ArtifactRef] {
        &self.derived_from
    }
}
