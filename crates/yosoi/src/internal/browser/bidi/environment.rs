//! Explicit native provenance, without fabricating Chrome/CDP renderer facts.

use super::session::{Page, Session, SessionError};
use crate::{
    browser::{BrowserEngine, BrowserExecutionIdentity, BrowserProtocol, MoliProfile},
    internal::{
        browser::{
            BrowserCaptureCapabilities, BrowserEnvironmentSnapshot, CapabilityState,
            CapabilityUnsupportedReason, ControllerVersion, EnvironmentObservation,
            EnvironmentUnavailableReason, InstrumentationMode, InstrumentationSnapshot,
            environment::{ENVIRONMENT_SNAPSHOT_JS, rendering_environment},
        },
        types::BrowserMode,
    },
};
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

pub const CONTROLLER_NAME: &str = "com.cascadinglabs.yosoi.bidi";
pub const CONTROLLER_VERSION: &str = env!("CARGO_PKG_VERSION");

impl Session {
    pub fn execution_identity(&self) -> BrowserExecutionIdentity {
        let identity = &self.identity;
        let config = &self.config;
        let owned = identity.executable.is_some();
        let profile = match (config.engine, config.moli_profile) {
            (BrowserEngine::Firefox, _) => Some("com.cascadinglabs.yosoi.bidi.firefox.core.v1"),
            (BrowserEngine::Moli, MoliProfile::Dom) => {
                Some("com.cascadinglabs.yosoi.bidi.moli.dom.v1")
            }
            (BrowserEngine::Moli, MoliProfile::Layout) => {
                Some("com.cascadinglabs.yosoi.bidi.moli.layout.v1")
            }
            (BrowserEngine::Chrome, _) => None,
        };
        BrowserExecutionIdentity {
            controller_version: Some(CONTROLLER_VERSION.to_owned()),
            capability_profile: profile.map(str::to_owned),
            reported_headless: identity.reported_headless,
            engine: config.engine,
            protocol: BrowserProtocol::Bidi,
            reported_name: identity.browser_name.clone(),
            reported_version: identity.browser_version.clone(),
            executable_version: identity
                .executable
                .as_ref()
                .map(|exe| exe.release_version.clone()),
            executable_sha256: identity.executable.as_ref().map(|exe| exe.sha256.clone()),
            process_owned: owned,
            moli_profile: (config.engine == BrowserEngine::Moli).then_some(config.moli_profile),
            moli_resources: (config.engine == BrowserEngine::Moli).then_some(config.moli_resources),
            owned_moli_private_network_blocking: (owned && config.engine == BrowserEngine::Moli)
                .then_some(!config.moli_allow_private_networks),
        }
    }
}

impl Page {
    pub async fn environment_snapshot(
        &self,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<BrowserEnvironmentSnapshot, SessionError> {
        let (value, _) = self
            .evaluate(ENVIRONMENT_SNAPSHOT_JS, cancellation, deadline)
            .await?;
        let identity = &self.session.identity;
        let owned = identity.executable.is_some();
        let headless = if owned {
            Some(!self.session.headful)
        } else {
            identity.reported_headless
        };
        let mode = match headless {
            Some(true) => EnvironmentObservation::Known {
                value: BrowserMode::Headless,
            },
            Some(false) => EnvironmentObservation::Known {
                value: BrowserMode::Headful,
            },
            None => EnvironmentObservation::Unavailable {
                reason: EnvironmentUnavailableReason::AttachedBrowserNotControlled,
            },
        };
        let backend = self.session.execution_identity();
        // These flags describe CDP instrumentation. BiDi script capability is
        // recorded separately; it must not imply Runtime.enable was issued.
        let instrumentation = InstrumentationSnapshot {
            configured_mode: InstrumentationMode::Normal,
            network_enabled: false,
            runtime_enabled: false,
            performance_enabled: false,
            log_enabled: false,
            target_auto_attach: false,
            utility_world_enabled: false,
            pre_navigation_stealth: false,
            attached_browser: !owned,
            escalated_from_minimal: false,
        };
        Ok(BrowserEnvironmentSnapshot {
            controller: ControllerVersion {
                name: CONTROLLER_NAME.into(),
                version: CONTROLLER_VERSION.into(),
            },
            renderer: None,
            backend: Some(backend),
            mode,
            rendering: rendering_environment(&value),
            instrumentation,
            capabilities: capabilities(
                self.session.config.engine,
                self.session.config.moli_profile,
            ),
        })
    }
}

pub const fn capabilities(
    engine: BrowserEngine,
    profile: MoliProfile,
) -> BrowserCaptureCapabilities {
    let supported = CapabilityState::Supported;
    let unsupported = CapabilityState::Unsupported {
        reason: CapabilityUnsupportedReason::NotImplemented,
    };
    let firefox = if matches!(engine, BrowserEngine::Firefox) {
        supported
    } else {
        CapabilityState::Unsupported {
            reason: CapabilityUnsupportedReason::EngineDoesNotReport,
        }
    };
    BrowserCaptureCapabilities {
        document_navigation: supported,
        document_response_metadata: firefox,
        selected_response_bodies: supported,
        document_source: firefox,
        rendered_dom: supported,
        accessibility_tree: CapabilityState::Unsupported {
            reason: CapabilityUnsupportedReason::ProtocolNotExposed,
        },
        out_of_process_frame_routing: supported,
        network_resource_graph: supported,
        cookies: unsupported,
        web_storage: unsupported,
        element_geometry: if matches!(engine, BrowserEngine::Firefox) {
            supported
        } else {
            CapabilityState::Unsupported {
                reason: CapabilityUnsupportedReason::RequiresRasterRefresh,
            }
        },
        screenshot: if matches!(engine, BrowserEngine::Firefox)
            || (matches!(engine, BrowserEngine::Moli) && matches!(profile, MoliProfile::Layout))
        {
            supported
        } else {
            CapabilityState::Unsupported {
                reason: CapabilityUnsupportedReason::RequiresLayoutProfile,
            }
        },
        screencast: CapabilityState::Unsupported {
            reason: CapabilityUnsupportedReason::ProtocolNotExposed,
        },
        runtime_diagnostics: supported,
    }
}
