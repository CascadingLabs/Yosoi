use crate::internal::types::{Producer, ProducerId, ProducerVersion, ReasonCode};

use crate::internal::direct_http::{
    AcquisitionCapabilityProfile, ArtifactCapability, ArtifactMultiplicity, CaptureEnvironment,
    EnvironmentValue, HttpCaptureEnvironment, UserAgent, WebArtifactCapabilitySet,
    WebProviderCapabilityProfile,
};

use super::DirectHttpTransportError;

/// Explicit environment and capability identities effective for a wreq attempt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DirectHttpExecutionIdentity {
    environment: CaptureEnvironment,
    capabilities: WebProviderCapabilityProfile,
    dependency: DirectHttpDependencyIdentity,
}

/// Concrete transport dependency used by the adapter.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DirectHttpDependencyIdentity {
    crate_name: &'static str,
    version: &'static str,
}

impl DirectHttpDependencyIdentity {
    pub const fn crate_name(&self) -> &'static str {
        self.crate_name
    }

    pub const fn version(&self) -> &'static str {
        self.version
    }
}

/// Returns the concrete adapter identity written into Direct HTTP receipts.
pub fn wreq_adapter_producer() -> Result<Producer, DirectHttpTransportError> {
    let id = ProducerId::new("com.cascadinglabs.yosoi.wreq-direct-http")
        .map_err(DirectHttpTransportError::identity)?;
    let version = ProducerVersion::new(env!("CARGO_PKG_VERSION"))
        .map_err(DirectHttpTransportError::identity)?;
    Ok(Producer::new(id, version))
}

impl DirectHttpExecutionIdentity {
    pub(in crate::internal::direct_http) fn new(
        user_agent: Option<&UserAgent>,
    ) -> Result<Self, DirectHttpTransportError> {
        let producer = wreq_adapter_producer()?;
        let unobserved = reason("web_capture.http.environment_not_observed")?;
        let unsupported = reason("web_capture.http.browser_runtime_unavailable")?;
        let supported = || ArtifactCapability::Supported {
            multiplicity: ArtifactMultiplicity::ExactlyOne,
        };
        let not_supported = || ArtifactCapability::Unsupported {
            reason: unsupported.clone(),
        };
        let artifacts = WebArtifactCapabilitySet::new(
            supported(),
            not_supported(),
            not_supported(),
            supported(),
            not_supported(),
            not_supported(),
            not_supported(),
            not_supported(),
            not_supported(),
        );
        let capabilities = WebProviderCapabilityProfile::new(
            producer.clone(),
            AcquisitionCapabilityProfile::DirectHttp,
            artifacts,
        )
        .map_err(DirectHttpTransportError::identity)?;
        let user_agent = user_agent.map_or_else(
            || EnvironmentValue::unavailable(unobserved.clone()),
            |value| EnvironmentValue::known(value.clone()),
        );
        let environment = CaptureEnvironment::Http(HttpCaptureEnvironment::new(
            producer,
            user_agent,
            EnvironmentValue::unavailable(unobserved),
        ));
        Ok(Self {
            environment,
            capabilities,
            dependency: DirectHttpDependencyIdentity {
                crate_name: "wreq",
                version: "0.16.1",
            },
        })
    }

    pub const fn environment(&self) -> &CaptureEnvironment {
        &self.environment
    }

    pub const fn capabilities(&self) -> &WebProviderCapabilityProfile {
        &self.capabilities
    }

    pub const fn dependency(&self) -> &DirectHttpDependencyIdentity {
        &self.dependency
    }
}

fn reason(value: &'static str) -> Result<ReasonCode, DirectHttpTransportError> {
    ReasonCode::new(value).map_err(DirectHttpTransportError::identity)
}
