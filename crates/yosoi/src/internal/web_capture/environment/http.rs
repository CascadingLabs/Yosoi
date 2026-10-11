use crate::internal::types::Producer;
use serde::{Deserialize, Serialize};

use super::{EnvironmentValue, PreferredLanguages, UserAgent};

/// Effective environment for a native HTTP capture.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HttpCaptureEnvironment {
    client: Producer,
    user_agent: EnvironmentValue<UserAgent>,
    preferred_languages: EnvironmentValue<PreferredLanguages>,
}

impl HttpCaptureEnvironment {
    /// Creates a native HTTP environment from explicit effective facts.
    pub const fn new(
        client: Producer,
        user_agent: EnvironmentValue<UserAgent>,
        preferred_languages: EnvironmentValue<PreferredLanguages>,
    ) -> Self {
        Self {
            client,
            user_agent,
            preferred_languages,
        }
    }

    /// Returns the HTTP implementation that interpreted the request.
    pub const fn client(&self) -> &Producer {
        &self.client
    }

    /// Returns the effective user agent state.
    pub const fn user_agent(&self) -> &EnvironmentValue<UserAgent> {
        &self.user_agent
    }

    /// Returns the effective ordered language preferences.
    pub const fn preferred_languages(&self) -> &EnvironmentValue<PreferredLanguages> {
        &self.preferred_languages
    }
}
