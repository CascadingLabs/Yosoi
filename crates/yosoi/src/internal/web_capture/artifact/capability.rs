use crate::internal::types::{Producer, ReasonCode};
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

use crate::internal::web_capture::BrowserMode;

use super::WebArtifactFamily;

/// Logical number of artifacts that one capability may emit.
///
/// This describes domain artifacts, not storage chunks used to encode one
/// large artifact.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ArtifactMultiplicity {
    /// A successful request emits exactly one logical artifact.
    ExactlyOne,
    /// A successful request may legitimately emit zero or one artifact.
    AtMostOne,
    /// A successful request may emit any number of deliberately scoped artifacts.
    Many,
}

/// Declared support for one artifact family by a provider profile.
///
/// Support is not proof that an individual attempt produced an artifact.
/// Runtime unavailability and policy omission belong to capture results.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum ArtifactCapability {
    /// The profile supports capture with the declared logical multiplicity.
    Supported {
        /// Number of logical artifacts that the profile may emit.
        multiplicity: ArtifactMultiplicity,
    },
    /// The provider profile cannot capture this family.
    Unsupported {
        /// Stable explanation of the missing support.
        reason: ReasonCode,
    },
}

impl ArtifactCapability {
    /// Returns whether the provider declares support for this family.
    pub const fn is_supported(&self) -> bool {
        matches!(self, Self::Supported { .. })
    }
}

/// Exhaustive artifact-family support for one provider acquisition profile.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WebArtifactCapabilitySet {
    source: ArtifactCapability,
    rendered_dom: ArtifactCapability,
    accessibility_tree: ArtifactCapability,
    network: ArtifactCapability,
    cookies: ArtifactCapability,
    storage: ArtifactCapability,
    layout: ArtifactCapability,
    visual: ArtifactCapability,
    runtime_diagnostics: ArtifactCapability,
}

impl WebArtifactCapabilitySet {
    /// Creates an exhaustive capability declaration.
    #[allow(clippy::too_many_arguments)]
    pub const fn new(
        source: ArtifactCapability,
        rendered_dom: ArtifactCapability,
        accessibility_tree: ArtifactCapability,
        network: ArtifactCapability,
        cookies: ArtifactCapability,
        storage: ArtifactCapability,
        layout: ArtifactCapability,
        visual: ArtifactCapability,
        runtime_diagnostics: ArtifactCapability,
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

    /// Returns source-content support.
    pub const fn source(&self) -> &ArtifactCapability {
        &self.source
    }

    /// Returns rendered-DOM support.
    pub const fn rendered_dom(&self) -> &ArtifactCapability {
        &self.rendered_dom
    }

    /// Returns accessibility-tree support.
    pub const fn accessibility_tree(&self) -> &ArtifactCapability {
        &self.accessibility_tree
    }

    /// Returns network-observation support.
    pub const fn network(&self) -> &ArtifactCapability {
        &self.network
    }

    /// Returns cookie-state support.
    pub const fn cookies(&self) -> &ArtifactCapability {
        &self.cookies
    }

    /// Returns web-storage support.
    pub const fn storage(&self) -> &ArtifactCapability {
        &self.storage
    }

    /// Returns layout-observation support.
    pub const fn layout(&self) -> &ArtifactCapability {
        &self.layout
    }

    /// Returns visual-artifact support.
    pub const fn visual(&self) -> &ArtifactCapability {
        &self.visual
    }

    /// Returns console and runtime-diagnostics support.
    pub const fn runtime_diagnostics(&self) -> &ArtifactCapability {
        &self.runtime_diagnostics
    }
}

/// Browser-mode constraint for document-navigation capabilities.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserNavigationCapabilityProfile {
    mode: BrowserMode,
}

impl BrowserNavigationCapabilityProfile {
    /// Creates a browser navigation profile for one effective mode.
    pub const fn new(mode: BrowserMode) -> Self {
        Self { mode }
    }

    /// Returns the effective browser mode represented by this profile.
    pub const fn mode(self) -> BrowserMode {
        self.mode
    }
}

/// Semantic acquisition mechanism scoped by a capability profile.
///
/// `wreq` and browser-driver names belong to [`Producer`]. Headless and
/// headful remain configurations of document navigation rather than separate
/// acquisition mechanisms.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(
    tag = "kind",
    content = "configuration",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum AcquisitionCapabilityProfile {
    /// Native non-browser HTTP acquisition.
    DirectHttp,
    /// HTTP associated with browser-context state without page execution.
    ContextBoundHttp,
    /// Fetch or XHR executing within an existing page context.
    PageContextFetch,
    /// Browser document navigation in a specific effective browser mode.
    DocumentNavigation(BrowserNavigationCapabilityProfile),
}

/// Error returned when a capability contradicts its acquisition semantics.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum WebProviderCapabilityProfileError {
    /// Non-browser HTTP claimed an artifact requiring browser page execution.
    #[error("{family:?} capability requires browser page execution")]
    BrowserArtifactOnHttpProfile {
        /// Contradictory family.
        family: WebArtifactFamily,
    },
}

/// Versioned provider declaration for one acquisition profile.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct WebProviderCapabilityProfile {
    producer: Producer,
    acquisition: AcquisitionCapabilityProfile,
    artifacts: WebArtifactCapabilitySet,
}

impl WebProviderCapabilityProfile {
    /// Creates a provider capability profile after checking inherent strategy semantics.
    pub fn new(
        producer: Producer,
        acquisition: AcquisitionCapabilityProfile,
        artifacts: WebArtifactCapabilitySet,
    ) -> Result<Self, WebProviderCapabilityProfileError> {
        validate_acquisition_capabilities(acquisition, &artifacts)?;
        Ok(Self {
            producer,
            acquisition,
            artifacts,
        })
    }

    /// Returns the provider implementation declaring support.
    pub const fn producer(&self) -> &Producer {
        &self.producer
    }

    /// Returns the semantic acquisition profile.
    pub const fn acquisition(&self) -> AcquisitionCapabilityProfile {
        self.acquisition
    }

    /// Returns the exhaustive artifact-family capability set.
    pub const fn artifacts(&self) -> &WebArtifactCapabilitySet {
        &self.artifacts
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WebProviderCapabilityProfileWire {
    producer: Producer,
    acquisition: AcquisitionCapabilityProfile,
    artifacts: WebArtifactCapabilitySet,
}

impl TryFrom<WebProviderCapabilityProfileWire> for WebProviderCapabilityProfile {
    type Error = WebProviderCapabilityProfileError;

    fn try_from(value: WebProviderCapabilityProfileWire) -> Result<Self, Self::Error> {
        Self::new(value.producer, value.acquisition, value.artifacts)
    }
}

impl<'de> Deserialize<'de> for WebProviderCapabilityProfile {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        WebProviderCapabilityProfileWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

fn validate_acquisition_capabilities(
    acquisition: AcquisitionCapabilityProfile,
    artifacts: &WebArtifactCapabilitySet,
) -> Result<(), WebProviderCapabilityProfileError> {
    if !matches!(
        acquisition,
        AcquisitionCapabilityProfile::DirectHttp | AcquisitionCapabilityProfile::ContextBoundHttp
    ) {
        return Ok(());
    }

    let browser_only = [
        (WebArtifactFamily::RenderedDom, artifacts.rendered_dom()),
        (
            WebArtifactFamily::AccessibilityTree,
            artifacts.accessibility_tree(),
        ),
        (WebArtifactFamily::Storage, artifacts.storage()),
        (WebArtifactFamily::Layout, artifacts.layout()),
        (WebArtifactFamily::Visual, artifacts.visual()),
        (
            WebArtifactFamily::RuntimeDiagnostics,
            artifacts.runtime_diagnostics(),
        ),
    ];
    for (family, capability) in browser_only {
        if capability.is_supported() {
            return Err(WebProviderCapabilityProfileError::BrowserArtifactOnHttpProfile { family });
        }
    }
    Ok(())
}
