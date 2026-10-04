use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

use super::{ArtifactRequest, WebArtifactFamily, WebArtifactRequestSet, WebArtifactResults};

/// Error returned when request intent and actual family results disagree.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum WebArtifactManifestError {
    /// An unrequested family reported an outcome other than `NotRequested`.
    #[error("unrequested {family:?} family cannot report an attempted result")]
    UnexpectedResult {
        /// Contradictory family.
        family: WebArtifactFamily,
    },
    /// A requested family was incorrectly reported as `NotRequested`.
    #[error("requested {family:?} family requires an explicit result")]
    MissingResult {
        /// Contradictory family.
        family: WebArtifactFamily,
    },
}

/// Validated pairing of artifact request intent and actual family results.
///
/// Required and optional requests may both end in complete, partial,
/// unavailable, policy-omitted, or unsupported results. Higher-level capture
/// finalization decides how those outcomes affect overall success.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct WebArtifactManifest {
    requests: WebArtifactRequestSet,
    results: WebArtifactResults,
}

impl WebArtifactManifest {
    /// Creates a manifest after checking every requested family has a result.
    pub fn new(
        requests: WebArtifactRequestSet,
        results: WebArtifactResults,
    ) -> Result<Self, WebArtifactManifestError> {
        validate_request_results(requests, &results)?;
        Ok(Self { requests, results })
    }

    /// Returns exhaustive caller intent.
    pub const fn requests(&self) -> &WebArtifactRequestSet {
        &self.requests
    }

    /// Returns exhaustive actual outcomes.
    pub const fn results(&self) -> &WebArtifactResults {
        &self.results
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WebArtifactManifestWire {
    requests: WebArtifactRequestSet,
    results: WebArtifactResults,
}

impl TryFrom<WebArtifactManifestWire> for WebArtifactManifest {
    type Error = WebArtifactManifestError;

    fn try_from(value: WebArtifactManifestWire) -> Result<Self, Self::Error> {
        Self::new(value.requests, value.results)
    }
}

impl<'de> Deserialize<'de> for WebArtifactManifest {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        WebArtifactManifestWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

fn validate_request_results(
    requests: WebArtifactRequestSet,
    results: &WebArtifactResults,
) -> Result<(), WebArtifactManifestError> {
    let families = [
        (
            WebArtifactFamily::Source,
            requests.source(),
            results.source().is_not_requested(),
        ),
        (
            WebArtifactFamily::RenderedDom,
            requests.rendered_dom(),
            results.rendered_dom().is_not_requested(),
        ),
        (
            WebArtifactFamily::AccessibilityTree,
            requests.accessibility_tree(),
            results.accessibility_tree().is_not_requested(),
        ),
        (
            WebArtifactFamily::Network,
            requests.network(),
            results.network().is_not_requested(),
        ),
        (
            WebArtifactFamily::Cookies,
            requests.cookies(),
            results.cookies().is_not_requested(),
        ),
        (
            WebArtifactFamily::Storage,
            requests.storage(),
            results.storage().is_not_requested(),
        ),
        (
            WebArtifactFamily::Layout,
            requests.layout(),
            results.layout().is_not_requested(),
        ),
        (
            WebArtifactFamily::Visual,
            requests.visual(),
            results.visual().is_not_requested(),
        ),
        (
            WebArtifactFamily::RuntimeDiagnostics,
            requests.runtime_diagnostics(),
            results.runtime_diagnostics().is_not_requested(),
        ),
    ];

    for (family, request, result_not_requested) in families {
        match (request, result_not_requested) {
            (ArtifactRequest::NotRequested, true)
            | (ArtifactRequest::Optional | ArtifactRequest::Required, false) => {}
            (ArtifactRequest::NotRequested, false) => {
                return Err(WebArtifactManifestError::UnexpectedResult { family });
            }
            (ArtifactRequest::Optional | ArtifactRequest::Required, true) => {
                return Err(WebArtifactManifestError::MissingResult { family });
            }
        }
    }
    Ok(())
}
