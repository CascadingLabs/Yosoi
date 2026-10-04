use yosoi_sdk::prelude as ys;

#[derive(ys::Contract)]
#[ys(id = "sdk-title", description = "SDK title", root = ys::locator::css("main"))]
struct Title {
    #[ys(description = "Heading", locator = ys::locator::css("h1").text())]
    heading: String,
}

#[test]
fn prelude_can_author_and_locate_without_an_internal_crate_import()
-> Result<(), Box<dyn std::error::Error>> {
    let document = ys::Document::html("sdk.html", b"<main><h1>SDK</h1></main>".to_vec())?;
    let plan = ys::Plan::new([ys::output("heading", ys::css("h1")?.text())?])?;
    let located = document.locate(&plan);
    let parsed = document.parse()?;
    let reused = parsed.locate(&plan);
    assert_eq!(located, reused);
    let contract = Title::locate(&document)?;
    let _ = contract;
    let _ = Title::plan()?;
    Ok(())
}

#[test]
fn sdk_namespaces_support_authoring() -> Result<(), Box<dyn std::error::Error>> {
    let mut policy = ys::policy::Policy::default();
    assert_eq!(policy.map.limits.max_concurrency.get(), 2);
    policy.map.limits.max_concurrency = ys::policy::Budget::new(4)?;
    policy.map.robots = ys::policy::Robots::Respect;
    let _skip_reason = ys::map::SourceSkipReason::NotSitemap;
    let _provider = ys::map::PublicProvider::SubdomainCenter;
    let _: fn(&ys::map::MapOutcome) -> &[ys::map::WildcardEntry] = ys::map::MapOutcome::wildcards;
    let _: fn(&ys::map::MapOutcome) -> &[ys::map::RequestTrace] = ys::map::MapOutcome::request_trace;
    let request = ys::request::new("https://example.com").bind(&policy);
    assert_eq!(request.target().as_str(), "https://example.com");
    let map = ys::map::new("https://example.com").bind(&policy);
    fn require_send(_future: impl std::future::Future + Send) {}
    require_send(map.send());
    Ok(())
}
