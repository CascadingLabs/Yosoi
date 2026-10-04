use serde::{Deserialize, Deserializer, de::Error as _};

use crate::{
    BrowserChallengeFact, BrowserExecutionReceipt, CaptureEnvironment, WebAcquisitionRecord,
    WebArtifactManifest, WebArtifactRelationship, WebProviderCapabilityProfile,
};

use super::{CaptureCompleteness, WebCapture, WebCaptureError};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WebCaptureData {
    acquisition: WebAcquisitionRecord,
    environment: CaptureEnvironment,
    observation: crate::CaptureObservation,
    capabilities: WebProviderCapabilityProfile,
    artifacts: WebArtifactManifest,
    relationships: Vec<WebArtifactRelationship>,
    completeness: CaptureCompleteness,
    #[serde(default)]
    browser_execution: Option<BrowserExecutionReceipt>,
    #[serde(default)]
    browser_challenge: Option<BrowserChallengeFact>,
}

impl<'de> Deserialize<'de> for WebCapture {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let data = WebCaptureData::deserialize(deserializer)?;
        let expected = data.completeness;
        let browser_execution = data.browser_execution;
        let browser_challenge = data.browser_challenge;
        let capture = Self::finalize(
            data.acquisition,
            data.environment,
            data.observation,
            data.capabilities,
            data.artifacts,
            data.relationships,
        )
        .map_err(D::Error::custom)?;
        if capture.completeness() != expected {
            return Err(D::Error::custom(WebCaptureError::CompletenessMismatch));
        }
        let capture = match browser_execution {
            Some(receipt) => capture.with_browser_execution(receipt),
            None => Ok(capture),
        }
        .map_err(D::Error::custom)?;
        match browser_challenge {
            Some(fact) => capture.with_browser_challenge(fact),
            None => Ok(capture),
        }
        .map_err(D::Error::custom)
    }
}
