use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

/// Error returned when a produced-artifact collection is empty.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
#[error("a complete or partial artifact-family result requires at least one artifact")]
pub struct ArtifactCollectionError;

/// Validated non-empty collection of artifacts from one family.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(transparent)]
pub struct ArtifactCollection<T>(Vec<T>);

impl<T> ArtifactCollection<T> {
    /// Creates a non-empty artifact collection.
    pub fn new(artifacts: Vec<T>) -> Result<Self, ArtifactCollectionError> {
        if artifacts.is_empty() {
            return Err(ArtifactCollectionError);
        }
        Ok(Self(artifacts))
    }

    /// Returns the family-typed artifacts.
    pub fn as_slice(&self) -> &[T] {
        &self.0
    }
}

impl<'de, T> Deserialize<'de> for ArtifactCollection<T>
where
    T: Deserialize<'de>,
{
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        Vec::<T>::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

impl<T> TryFrom<Vec<T>> for ArtifactCollection<T> {
    type Error = ArtifactCollectionError;

    fn try_from(value: Vec<T>) -> Result<Self, Self::Error> {
        Self::new(value)
    }
}

impl<T> From<ArtifactCollection<T>> for Vec<T> {
    fn from(value: ArtifactCollection<T>) -> Self {
        value.0
    }
}

/// Caller intent for one artifact family.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ArtifactRequest {
    /// Do not attempt this family.
    NotRequested,
    /// Capture when supported, but do not fail the overall intent if absent.
    Optional,
    /// The caller requires an explicit result for this family.
    Required,
}

/// Exhaustive artifact-family request for one capture attempt.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WebArtifactRequestSet {
    source: ArtifactRequest,
    rendered_dom: ArtifactRequest,
    accessibility_tree: ArtifactRequest,
    network: ArtifactRequest,
    cookies: ArtifactRequest,
    storage: ArtifactRequest,
    layout: ArtifactRequest,
    visual: ArtifactRequest,
    runtime_diagnostics: ArtifactRequest,
}

impl WebArtifactRequestSet {
    /// Creates an exhaustive artifact request.
    #[allow(clippy::too_many_arguments)]
    pub const fn new(
        source: ArtifactRequest,
        rendered_dom: ArtifactRequest,
        accessibility_tree: ArtifactRequest,
        network: ArtifactRequest,
        cookies: ArtifactRequest,
        storage: ArtifactRequest,
        layout: ArtifactRequest,
        visual: ArtifactRequest,
        runtime_diagnostics: ArtifactRequest,
    ) -> Self {
        Self {
            source,
            rendered_dom,
            accessibility_tree,
            network,
            cookies,
            storage,
            layout,
            visual,
            runtime_diagnostics,
        }
    }

    /// Returns source-content intent.
    pub const fn source(self) -> ArtifactRequest {
        self.source
    }

    /// Returns rendered-DOM intent.
    pub const fn rendered_dom(self) -> ArtifactRequest {
        self.rendered_dom
    }

    /// Returns accessibility-tree intent.
    pub const fn accessibility_tree(self) -> ArtifactRequest {
        self.accessibility_tree
    }

    /// Returns network-observation intent.
    pub const fn network(self) -> ArtifactRequest {
        self.network
    }

    /// Returns cookie-state intent.
    pub const fn cookies(self) -> ArtifactRequest {
        self.cookies
    }

    /// Returns web-storage intent.
    pub const fn storage(self) -> ArtifactRequest {
        self.storage
    }

    /// Returns layout-observation intent.
    pub const fn layout(self) -> ArtifactRequest {
        self.layout
    }

    /// Returns visual-artifact intent.
    pub const fn visual(self) -> ArtifactRequest {
        self.visual
    }

    /// Returns runtime-diagnostics intent.
    pub const fn runtime_diagnostics(self) -> ArtifactRequest {
        self.runtime_diagnostics
    }
}
