use std::num::NonZeroU16;

use serde::{Deserialize, Serialize};

use crate::{
    PolicyError,
    policy::{Acquisition, BrowserMode, DocumentRequest, Documents, MaximumElapsed, Page, Request},
};

/// Version of the provider-default registry used by effective Search snapshots.
pub const PROVIDER_DEFAULTS_REGISTRY_VERSION: u16 = 4;

/// A supported Search provider.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Provider {
    Brave,
    Bing,
    DuckDuckGo,
}

impl Provider {
    /// Returns the versioned local profile's current certification state.
    pub fn defaults_status(self) -> ProviderDefaultsStatus {
        let version = match self {
            Self::Brave | Self::Bing => NonZeroU16::new(2).unwrap_or(NonZeroU16::MIN),
            Self::DuckDuckGo => NonZeroU16::MIN,
        };
        ProviderDefaultsStatus::Preview {
            version: ProviderDefaultsVersion(version),
        }
    }

    pub(super) fn current_profile(self) -> ProviderRequestProfile {
        let mut request = Request::default();
        let page = match self {
            Self::Bing => Page::default(),
            Self::Brave | Self::DuckDuckGo => {
                request.maximum_elapsed = MaximumElapsed::default_search_browser_request();
                Page {
                    acquisitions: vec![Acquisition::Browser(BrowserMode::Headless).documents([
                        DocumentRequest::ResponseDocument,
                        DocumentRequest::RenderedDom,
                    ])],
                }
            }
        };
        ProviderRequestProfile {
            page,
            request,
            documents: Documents::default(),
        }
    }
}

/// A version identifier for one certified provider Requests profile.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(transparent)]
pub struct ProviderDefaultsVersion(NonZeroU16);

impl ProviderDefaultsVersion {
    /// Creates a positive provider-default version.
    pub fn try_new(version: u16) -> Result<Self, PolicyError> {
        NonZeroU16::new(version)
            .map(Self)
            .ok_or(PolicyError::ZeroProviderDefaultsVersion)
    }

    /// Returns the positive version number.
    pub const fn get(self) -> u16 {
        self.0.get()
    }
}

/// Whether the provider registry can supply a certified Current profile.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum ProviderDefaultsStatus {
    /// No certified Current profile is available in this registry revision.
    Unavailable { registry_version: u16 },
    /// A versioned local profile is available while certification remains open.
    Preview { version: ProviderDefaultsVersion },
    /// A certified Current profile is available at this provider version.
    Certified { version: ProviderDefaultsVersion },
    /// The route was pinned explicitly and does not use provider defaults.
    Exact,
}

/// Whether a provider selection was authored as Current or Exact.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProfileSelectionKind {
    Current,
    Exact,
}

/// A complete existing Requests policy profile for one provider.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProviderRequestProfile {
    /// Acquisition and requested-document choices.
    pub page: Page,
    /// Request deadline, transport limits, and redirect behavior.
    pub request: Request,
    /// Document parsing limits.
    pub documents: Documents,
}

impl ProviderRequestProfile {
    /// Creates a complete Requests profile and validates its nested policy.
    pub fn new(page: Page, request: Request, documents: Documents) -> Result<Self, PolicyError> {
        page.validate()?;
        request.validate()?;
        Ok(Self {
            page,
            request,
            documents,
        })
    }

    /// Returns the acquisition and requested-document choices.
    pub const fn page(&self) -> &Page {
        &self.page
    }

    /// Returns request deadlines, transport limits, and redirect behavior.
    pub const fn request(&self) -> &Request {
        &self.request
    }

    /// Returns document parsing limits.
    pub const fn documents(&self) -> &Documents {
        &self.documents
    }

    pub(super) fn validate(&self) -> Result<(), PolicyError> {
        self.page.validate()?;
        self.request.validate()
    }
}

/// One provider in authored response order, with its Requests profile choice.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProviderSelection {
    /// Provider whose result slot occupies this position.
    pub provider: Provider,
    /// Current certified defaults or a complete explicit Requests profile.
    pub profile: ProfileSelection,
}

impl ProviderSelection {
    /// Selects the provider's current certified Requests profile.
    pub const fn current(provider: Provider) -> Self {
        Self {
            provider,
            profile: ProfileSelection::Current,
        }
    }

    /// Selects a complete explicit Requests profile for the provider.
    pub const fn exact(provider: Provider, profile: ProviderRequestProfile) -> Self {
        Self {
            provider,
            profile: ProfileSelection::Exact(profile),
        }
    }
}

/// How Search obtains one provider's Requests profile.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(
    tag = "kind",
    content = "profile",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum ProfileSelection {
    /// Resolve the provider's current certified Requests profile.
    Current,
    /// Pin one complete general Requests profile in the Search policy.
    Exact(ProviderRequestProfile),
}

impl ProfileSelection {
    /// Returns whether this is a Current or Exact profile declaration.
    pub const fn kind(&self) -> ProfileSelectionKind {
        match self {
            Self::Current => ProfileSelectionKind::Current,
            Self::Exact(_) => ProfileSelectionKind::Exact,
        }
    }
}
