//! Select an optional browser engine and its explicit execution profile.
//!
//! Browser capability does not grant permission: the acquisition and retained
//! Session policies still bound every operation. Selecting an optional engine
//! never installs a binary or silently falls back to another controller.

use std::{fmt, path::PathBuf};

use serde::{Deserialize, Serialize};
use thiserror::Error;

/// The browser implementation used for a browser acquisition or retained Session.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserEngine {
    /// The existing regular Chrome/Chromium Stable implementation over CDP.
    #[default]
    Chrome,
    /// A regular Firefox release controlled through native WebDriver BiDi.
    Firefox,
    /// A pinned Moli release controlled through native WebDriver BiDi.
    Moli,
}

impl BrowserEngine {
    /// Returns the controller supported by this engine selection.
    pub const fn protocol(self) -> BrowserProtocol {
        match self {
            Self::Chrome => BrowserProtocol::Cdp,
            Self::Firefox | Self::Moli => BrowserProtocol::Bidi,
        }
    }
}

/// The private controller's wire protocol, recorded separately from engine identity.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserProtocol {
    /// Chrome DevTools Protocol through the existing Chromiumoxide integration.
    Cdp,
    /// WebDriver BiDi through the optional shared controller.
    Bidi,
}

/// Moli's rendering capability, independent of headless/headful window mode.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MoliProfile {
    /// DOM/script operations without claiming accurate geometry or rendered pixels.
    #[default]
    Dom,
    /// Enable Moli's on-demand layout and visual surfaces.
    Layout,
}

/// Engine provenance retained independently of page-visible identity strings.
///
/// Protocol fields are the server's claims. Executable fields describe only an
/// owned local executable admitted by Yosoi. Neither a configured endpoint nor
/// a page's user agent proves the identity or network policy of a remote server.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserExecutionIdentity {
    /// Linked native controller version, absent in older evidence.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub controller_version: Option<String>,
    /// Selected versioned controller capability contract, not remote attestation.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub capability_profile: Option<String>,
    /// Native server's reported headless flag, when supplied.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reported_headless: Option<bool>,
    /// Engine selected by the caller.
    pub engine: BrowserEngine,
    /// Actual controller transport used for this execution.
    pub protocol: BrowserProtocol,
    /// Browser name reported by native session negotiation, when provided.
    pub reported_name: Option<String>,
    /// Browser version reported by native session negotiation, when provided.
    pub reported_version: Option<String>,
    /// Admitted owned executable's release version; absent for external services.
    pub executable_version: Option<String>,
    /// SHA-256 of the admitted owned executable; absent for external services.
    pub executable_sha256: Option<String>,
    /// Whether this execution owned the process, rather than just logical contexts.
    pub process_owned: bool,
    /// Declared Moli rendering profile; absent for other engines.
    pub moli_profile: Option<MoliProfile>,
    /// Declared Moli resource loading profile; absent for other engines.
    pub moli_resources: Option<bool>,
    /// Native private-network blocking flag of an owned Moli launch.
    /// External services have no client-observed enforcement claim here.
    pub owned_moli_private_network_blocking: Option<bool>,
}

/// Browser acquisition settings shared by Requests and retained Sessions.
///
/// Chrome/CDP is the default. Firefox and Moli require the `browser-bidi` Cargo
/// feature at execution time and an explicitly installed executable, or an
/// explicitly configured BiDi service. Parsing a declaration does not require
/// that feature, so archived policies can be inspected without launching browsers.
#[derive(Clone, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct BrowserConfig {
    /// The selected implementation; omitted declarations retain Chrome/CDP.
    pub engine: BrowserEngine,
    /// An absolute executable path, or normal engine discovery when omitted.
    pub executable: Option<PathBuf>,
    /// An existing BiDi service's WebSocket URL; its process is never owned.
    ///
    /// Use `/session` for the native Firefox/Moli servers. User information,
    /// query strings and fragments are rejected rather than retained as secrets
    /// in policy identities. Endpoint selection is not executable attestation.
    pub endpoint: Option<String>,
    /// Whether Moli may construct accurate layout; valid only for Moli.
    pub moli_profile: MoliProfile,
    /// Load optional Moli image/font/media resources; valid only for Moli.
    pub moli_resources: bool,
    /// Deliberately allow private-network requests in an owned Moli process.
    ///
    /// The default owned launch uses Moli's private-network blocking. A shared
    /// external service must declare/enforce its own network profile; a client
    /// connection cannot prove its server's operating-system egress policy.
    pub moli_allow_private_networks: bool,
}

impl fmt::Debug for BrowserConfig {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BrowserConfig")
            .field("engine", &self.engine)
            .field("executable", &self.executable)
            .field("endpoint", &self.endpoint.as_ref().map(|_| "<configured>"))
            .field("moli_profile", &self.moli_profile)
            .field("moli_resources", &self.moli_resources)
            .field(
                "moli_allow_private_networks",
                &self.moli_allow_private_networks,
            )
            .finish()
    }
}

/// A structurally invalid browser declaration, before any process or action starts.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BrowserConfigurationError {
    /// Owned executable launch and connection to an existing service conflict.
    #[error("choose either a browser executable or an existing BiDi endpoint")]
    ConflictingLaunchSources,
    /// Explicit executable paths must identify a concrete local file.
    #[error("an explicit browser executable path must be absolute")]
    RelativeExecutable,
    /// The endpoint is not an unambiguous, secret-free WebSocket service URL.
    #[error("browser endpoint must be a ws/wss URL without user information, query or fragment")]
    InvalidEndpoint,
    /// The current Chrome provider is not an externally attached BiDi provider.
    #[error("BiDi endpoints require the Firefox or Moli engine")]
    EndpointRequiresBidi,
    /// Rendering/resource/network options must not be silently ignored.
    #[error("Moli-specific options require the Moli engine")]
    MoliOptionsRequireMoli,
    /// Moli has no native desktop browser window.
    #[error("Moli supports headless execution only")]
    MoliHeadfulUnsupported,
}

impl BrowserConfig {
    /// Whether the owned TCP relay can be reached and scoped by this provider.
    pub(crate) fn supports_owned_network_route(&self) -> bool {
        self.engine == BrowserEngine::Chrome
            || (self.engine == BrowserEngine::Firefox && self.endpoint.is_none())
    }

    /// Tests whether serialization may omit this legacy-compatible default.
    pub fn is_default(&self) -> bool {
        self == &Self::default()
    }

    /// Validates the declaration without I/O, binary discovery or feature admission.
    pub fn validate(&self) -> Result<(), BrowserConfigurationError> {
        if self.executable.is_some() && self.endpoint.is_some() {
            return Err(BrowserConfigurationError::ConflictingLaunchSources);
        }
        if self
            .executable
            .as_ref()
            .is_some_and(|path| !path.is_absolute())
        {
            return Err(BrowserConfigurationError::RelativeExecutable);
        }
        if let Some(endpoint) = &self.endpoint {
            if endpoint.len() > 4096 {
                return Err(BrowserConfigurationError::InvalidEndpoint);
            }
            if self.engine.protocol() != BrowserProtocol::Bidi {
                return Err(BrowserConfigurationError::EndpointRequiresBidi);
            }
            let url = url::Url::parse(endpoint)
                .map_err(|_| BrowserConfigurationError::InvalidEndpoint)?;
            if !matches!(url.scheme(), "ws" | "wss")
                || url.host_str().is_none()
                || !url.username().is_empty()
                || url.password().is_some()
                || url.query().is_some()
                || url.fragment().is_some()
            {
                return Err(BrowserConfigurationError::InvalidEndpoint);
            }
        }
        if self.engine != BrowserEngine::Moli
            && (self.moli_profile != MoliProfile::Dom
                || self.moli_resources
                || self.moli_allow_private_networks)
        {
            return Err(BrowserConfigurationError::MoliOptionsRequireMoli);
        }
        Ok(())
    }

    /// Validates the selected window mode before launch or endpoint admission.
    pub fn validate_headful(&self, headful: bool) -> Result<(), BrowserConfigurationError> {
        self.validate()?;
        if headful && self.engine == BrowserEngine::Moli {
            return Err(BrowserConfigurationError::MoliHeadfulUnsupported);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::policy;
    use std::error as std_error;

    #[test]
    fn selection_is_not_an_implicit_protocol_or_window_fallback() {
        assert!(BrowserConfig::default().is_default());
        assert_eq!(BrowserEngine::Chrome.protocol(), BrowserProtocol::Cdp);
        assert_eq!(BrowserEngine::Firefox.protocol(), BrowserProtocol::Bidi);
        let moli = BrowserConfig {
            engine: BrowserEngine::Moli,
            ..BrowserConfig::default()
        };
        assert_eq!(
            moli.validate_headful(true),
            Err(BrowserConfigurationError::MoliHeadfulUnsupported)
        );
        assert!(moli.validate_headful(false).is_ok());
    }

    #[test]
    fn archived_optional_configuration_parses_without_launching_a_binary() {
        let parsed = serde_json::from_str::<BrowserConfig>(
            r#"{"engine":"moli","moli_profile":"layout","moli_resources":true}"#,
        );
        assert!(parsed.is_ok_and(|value| value.validate().is_ok()));
        assert!(
            serde_json::from_str::<BrowserConfig>(r#"{"engine":"moli","protocol":"cdp"}"#).is_err()
        );
    }

    #[test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Policy identity contract assertions."
    )]
    fn optional_policy_identity_is_bound_without_changing_legacy_defaults()
    -> Result<(), Box<dyn std_error::Error>> {
        let baseline = policy::Policy::default();
        assert_eq!(baseline.effective_identity()?.version(), 7);
        let canonical: serde_json::Value = serde_json::from_str(&baseline.to_canonical_json()?)?;
        assert!(canonical.get("browser").is_none());
        let mut configured = baseline.clone();
        configured.browser.engine = BrowserEngine::Firefox;
        let identity = configured.effective_identity()?;
        assert_eq!(identity.version(), 8);
        assert_ne!(identity.digest(), baseline.effective_identity()?.digest());
        assert!(configured.archived_v6_identity().is_err());
        let parsed: policy::Policy = serde_json::from_str(&configured.to_canonical_json()?)?;
        assert_eq!(parsed.effective_identity()?, identity);
        let mut mismatched = parsed.effective_policy()?;
        mismatched.browser = BrowserConfig::default();
        assert!(parsed.validate_effective_snapshot(&mismatched).is_err());
        Ok(())
    }

    #[test]
    fn moli_headful_policy_is_rejected_before_any_browser_launch() {
        let mut policy = policy::Policy::default();
        policy.browser.engine = BrowserEngine::Moli;
        policy.page.acquisitions = vec![policy::Acquisition::Browser(policy::BrowserMode::Headful)];
        assert!(matches!(
            policy.validate(),
            Err(policy::PolicyError::BrowserConfiguration(
                BrowserConfigurationError::MoliHeadfulUnsupported
            ))
        ));
    }

    #[test]
    fn endpoint_secrets_and_ambiguous_ownership_are_rejected() {
        for endpoint in [
            "http://localhost/session",
            "ws://user:secret@localhost/session",
            "wss://example.test/session?token=secret",
            "ws://localhost/session#secret",
        ] {
            let config = BrowserConfig {
                engine: BrowserEngine::Moli,
                endpoint: Some(endpoint.into()),
                ..BrowserConfig::default()
            };
            assert_eq!(
                config.validate(),
                Err(BrowserConfigurationError::InvalidEndpoint)
            );
            assert!(!format!("{config:?}").contains("secret"));
        }
        let config = BrowserConfig {
            engine: BrowserEngine::Firefox,
            executable: Some(PathBuf::from("/browser")),
            endpoint: Some("ws://localhost/session".into()),
            ..BrowserConfig::default()
        };
        assert_eq!(
            config.validate(),
            Err(BrowserConfigurationError::ConflictingLaunchSources)
        );
    }
}
