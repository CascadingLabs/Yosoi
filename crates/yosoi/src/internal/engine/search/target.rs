use crate::internal::policy::policy::search::Provider;
use crate::internal::web_capture::{RequestedWebTarget, WebUrlParseError};
use thiserror::Error;
use url::Url;

/// A checked failure constructing one provider's fixed Search endpoint.
#[derive(Debug, Error)]
pub enum ProviderTargetError {
    #[error("Search provider endpoint is invalid")]
    Endpoint(#[source] url::ParseError),
    #[error("Search provider target is invalid")]
    Target(#[source] WebUrlParseError),
}

/// Constructs one provider target without a parallel HTTP path or unescaped
/// query-string concatenation. Google is deliberately absent from Provider.
pub fn provider_target(
    provider: Provider,
    query: &str,
) -> Result<RequestedWebTarget, ProviderTargetError> {
    let base = match provider {
        Provider::Brave => "https://search.brave.com/search",
        Provider::Bing => "https://www.bing.com/search",
        Provider::DuckDuckGo => "https://duckduckgo.com/",
    };
    let mut url = Url::parse(base).map_err(ProviderTargetError::Endpoint)?;
    url.query_pairs_mut().append_pair("q", query);
    RequestedWebTarget::parse(url.as_str()).map_err(ProviderTargetError::Target)
}

#[cfg(test)]
#[expect(
    clippy::panic_in_result_fn,
    reason = "assertions report provider-target encoding regressions after fallible setup"
)]
mod tests {
    use std::error::Error;

    use crate::internal::policy::policy::search::Provider;

    use super::provider_target;

    #[test]
    fn provider_targets_escape_query_intent() -> Result<(), Box<dyn Error>> {
        for provider in [Provider::Brave, Provider::Bing, Provider::DuckDuckGo] {
            let target = provider_target(provider, "rust & ownership")?;
            assert!(target.as_str().contains("q=rust+%26+ownership"));
        }
        Ok(())
    }
}
