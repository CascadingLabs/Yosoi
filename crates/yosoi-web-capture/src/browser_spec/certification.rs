use super::families::{FAMILIES, family_index, profile_capability};
use crate::{
    AcquisitionCapabilityProfile, ArtifactCapability, BrowserMode, WebArtifactFamily,
    WebProviderCapabilityProfile,
};
use thiserror::Error;
use yosoi_types::{Producer, ReasonCode};
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BrowserInstrumentationMode {
    Normal,
    Minimal,
    MinimalNetworkEscalated,
    MinimalRuntimeEscalated,
    MinimalBothEscalated,
}
impl BrowserInstrumentationMode {
    const fn network_enabled(self) -> bool {
        matches!(
            self,
            Self::Normal | Self::MinimalNetworkEscalated | Self::MinimalBothEscalated
        )
    }
    const fn runtime_enabled(self) -> bool {
        matches!(
            self,
            Self::Normal | Self::MinimalRuntimeEscalated | Self::MinimalBothEscalated
        )
    }
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BrowserCapabilityStatus {
    Supported,
    Disabled { reason: ReasonCode },
    Unavailable { reason: ReasonCode },
    Unsupported { reason: ReasonCode },
}
impl BrowserCapabilityStatus {
    pub const fn is_supported(&self) -> bool {
        matches!(self, Self::Supported)
    }
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserFamilyCapabilities {
    states: [BrowserCapabilityStatus; 9],
}
impl BrowserFamilyCapabilities {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        source: BrowserCapabilityStatus,
        rendered_dom: BrowserCapabilityStatus,
        accessibility_tree: BrowserCapabilityStatus,
        network: BrowserCapabilityStatus,
        cookies: BrowserCapabilityStatus,
        storage: BrowserCapabilityStatus,
        layout: BrowserCapabilityStatus,
        visual: BrowserCapabilityStatus,
        runtime_diagnostics: BrowserCapabilityStatus,
    ) -> Self {
        Self {
            states: [
                source,
                rendered_dom,
                accessibility_tree,
                network,
                cookies,
                storage,
                layout,
                visual,
                runtime_diagnostics,
            ],
        }
    }
    pub fn get(&self, family: WebArtifactFamily) -> Option<&BrowserCapabilityStatus> {
        self.states.get(family_index(family))
    }
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CertifiedBrowserCapabilities {
    profile: WebProviderCapabilityProfile,
    instrumentation: BrowserInstrumentationMode,
    families: BrowserFamilyCapabilities,
}
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BrowserCertificationError {
    #[error("capability producer does not match certified producer")]
    ProducerMismatch,
    #[error("capability acquisition is not document navigation")]
    AcquisitionMismatch,
    #[error("capability browser mode does not match certified mode")]
    ModeMismatch,
    #[error("declared state contradicts provider capability for {family:?}")]
    FamilyMismatch { family: WebArtifactFamily },
}
impl CertifiedBrowserCapabilities {
    pub fn new(
        profile: WebProviderCapabilityProfile,
        producer: &Producer,
        mode: BrowserMode,
        instrumentation: BrowserInstrumentationMode,
        families: BrowserFamilyCapabilities,
    ) -> Result<Self, BrowserCertificationError> {
        if profile.producer() != producer {
            return Err(BrowserCertificationError::ProducerMismatch);
        }
        match profile.acquisition() {
            AcquisitionCapabilityProfile::DocumentNavigation(p) if p.mode() == mode => {}
            AcquisitionCapabilityProfile::DocumentNavigation(_) => {
                return Err(BrowserCertificationError::ModeMismatch);
            }
            _ => return Err(BrowserCertificationError::AcquisitionMismatch),
        }
        for family in FAMILIES {
            let provider = profile_capability(&profile, family);
            let status = families.get(family);
            let agrees = match provider {
                ArtifactCapability::Supported { .. } => {
                    !matches!(status, Some(BrowserCapabilityStatus::Unsupported { .. }))
                }
                ArtifactCapability::Unsupported { .. } => {
                    matches!(status, Some(BrowserCapabilityStatus::Unsupported { .. }))
                }
            };
            if !agrees {
                return Err(BrowserCertificationError::FamilyMismatch { family });
            }
        }
        for family in FAMILIES {
            let status = families.get(family);
            let expected_enabled = match family {
                WebArtifactFamily::Source | WebArtifactFamily::Network => {
                    Some(instrumentation.network_enabled())
                }
                WebArtifactFamily::RuntimeDiagnostics => Some(instrumentation.runtime_enabled()),
                _ => None,
            };
            let valid = if family == WebArtifactFamily::Storage {
                matches!(status, Some(BrowserCapabilityStatus::Unsupported { .. }))
            } else if let Some(enabled) = expected_enabled {
                enabled == matches!(status, Some(BrowserCapabilityStatus::Supported))
            } else {
                matches!(status, Some(BrowserCapabilityStatus::Supported))
            };
            if !valid {
                return Err(BrowserCertificationError::FamilyMismatch { family });
            }
        }
        if families
            .get(WebArtifactFamily::Source)
            .map(BrowserCapabilityStatus::is_supported)
            != families
                .get(WebArtifactFamily::Network)
                .map(BrowserCapabilityStatus::is_supported)
        {
            return Err(BrowserCertificationError::FamilyMismatch {
                family: WebArtifactFamily::Network,
            });
        }
        Ok(Self {
            profile,
            instrumentation,
            families,
        })
    }
    pub const fn profile(&self) -> &WebProviderCapabilityProfile {
        &self.profile
    }
    pub const fn instrumentation(&self) -> BrowserInstrumentationMode {
        self.instrumentation
    }
    pub const fn families(&self) -> &BrowserFamilyCapabilities {
        &self.families
    }
}
