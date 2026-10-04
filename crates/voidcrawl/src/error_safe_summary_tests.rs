use super::*;

#[test]
fn safe_summaries_have_stable_codes_and_categories() {
    let renderer_crashed = VoidCrawlError::RendererCrashed;
    assert_eq!(
        renderer_crashed.code().as_str(),
        "voidcrawl.renderer.crashed"
    );
    assert_eq!(
        renderer_crashed.category(),
        VoidCrawlErrorCategory::ProviderFailure
    );
    assert_eq!(renderer_crashed.safe_message(), "page renderer crashed");
    let summary = serde_json::to_string(&renderer_crashed.safe_summary())
        .expect("serialize renderer crash summary");
    assert!(summary.contains("voidcrawl.renderer.crashed"));
    assert!(summary.contains("provider_failure"));
    assert!(summary.contains("page renderer crashed"));

    let timeout = VoidCrawlError::NavigationTimeout {
        url: "https://example.test/?token=secret".into(),
        wait_phase: "networkidle".into(),
        timeout_secs: 1.0,
        elapsed_secs: 1.0,
    };
    assert_eq!(timeout.code().as_str(), "voidcrawl.navigation.timeout");
    assert_eq!(timeout.category(), VoidCrawlErrorCategory::Timeout);

    let interrupted = VoidCrawlError::SessionInterrupted {
        interrupt_id: "secret-id".into(),
    };
    assert_eq!(interrupted.code().as_str(), "voidcrawl.interrupt.active");
    assert_eq!(interrupted.category(), VoidCrawlErrorCategory::Interrupted);

    let unavailable = VoidCrawlError::ProfileNotFound {
        name: "private-profile".into(),
        searched: vec!["/home/private/profile".into()],
    };
    assert_eq!(unavailable.category(), VoidCrawlErrorCategory::Unavailable);
}
