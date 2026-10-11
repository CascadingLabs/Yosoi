#[cfg(feature = "browser")]
use crate::internal::browser as void_crawl_core;

use super::*;

#[test]
fn provider_error_categories_are_closed_and_secret_safe() {
    use VoidCrawlAdapterErrorCategory as Category;
    let cases = [
        (
            void_crawl_core::VoidCrawlError::InvalidInput {
                operation: "x",
                reason: "secret",
            },
            Category::InvalidInput,
        ),
        (
            void_crawl_core::VoidCrawlError::UnsupportedVisualTarget,
            Category::Unsupported,
        ),
        (
            void_crawl_core::VoidCrawlError::Timeout("secret".to_owned()),
            Category::Timeout,
        ),
        (
            void_crawl_core::VoidCrawlError::SessionInterrupted {
                interrupt_id: "secret".to_owned(),
            },
            Category::Interrupted,
        ),
        (
            void_crawl_core::VoidCrawlError::FrameNotFound("secret".to_owned()),
            Category::Unavailable,
        ),
        (
            void_crawl_core::VoidCrawlError::PageError("secret".to_owned()),
            Category::ProviderFailure,
        ),
        (
            void_crawl_core::VoidCrawlError::Other("secret".to_owned()),
            Category::Internal,
        ),
    ];
    for (provider_error, expected) in cases {
        let mapped = conversions::map_provider_error(&provider_error);
        assert!(
            matches!(mapped, VoidCrawlAdapterError::Provider { category, .. } if category == expected)
        );
        assert!(!mapped.to_string().contains("secret"));
        assert!(!format!("{mapped:?}").contains("secret"));
    }
}

#[test]
fn provider_secret_does_not_enter_adapter_error() {
    let secret = "CAS329_SECRET_SENTINEL";
    let provider_error = void_crawl_core::VoidCrawlError::PageError(secret.to_owned());
    let mapped = conversions::map_provider_error(&provider_error);
    assert!(!format!("{mapped:?}").contains(secret));
    assert!(!mapped.to_string().contains(secret));
}
