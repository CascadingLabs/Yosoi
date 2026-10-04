use thiserror::Error;
use void_crawl_core as provider;
use yosoi_types::{Producer, ProducerId, ProducerVersion};

#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum VoidCrawlAdapterProducerError {
    #[error("VoidCrawl adapter producer ID is invalid")]
    InvalidId(#[source] yosoi_types::NamespacedIdError),
    #[error("VoidCrawl adapter producer version is invalid")]
    InvalidVersion(#[source] yosoi_types::ProducerVersionError),
}

/// Canonical producer identity shared by standard setup and runtime evidence.
pub fn void_crawl_adapter_producer() -> Result<Producer, VoidCrawlAdapterProducerError> {
    let id = ProducerId::new("com.cascadinglabs.void_crawl_core")
        .map_err(VoidCrawlAdapterProducerError::InvalidId)?;
    let version = ProducerVersion::new(provider::VOID_CRAWL_VERSION)
        .map_err(VoidCrawlAdapterProducerError::InvalidVersion)?;
    Ok(Producer::new(id, version))
}

#[cfg(test)]
mod tests {
    use std::error::Error;

    use super::*;

    #[test]
    #[allow(clippy::panic_in_result_fn)]
    fn canonical_identity_tracks_the_linked_voidcrawl_package() -> Result<(), Box<dyn Error>> {
        let producer = void_crawl_adapter_producer()?;
        assert_eq!(producer.id().as_str(), "com.cascadinglabs.void_crawl_core");
        assert_eq!(producer.version().as_str(), provider::VOID_CRAWL_VERSION);
        Ok(())
    }
}
