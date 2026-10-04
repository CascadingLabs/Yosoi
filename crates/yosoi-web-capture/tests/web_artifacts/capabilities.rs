use serde_json::json;
use yosoi_web_capture::{
    AcquisitionCapabilityProfile, ArtifactCapability, ArtifactMultiplicity, BrowserMode,
    BrowserNavigationCapabilityProfile, WebArtifactCapabilitySet, WebArtifactFamily,
    WebProviderCapabilityProfile, WebProviderCapabilityProfileError,
};

use super::support::{producer, reason};

const fn supported(multiplicity: ArtifactMultiplicity) -> ArtifactCapability {
    ArtifactCapability::Supported { multiplicity }
}

fn unsupported(family: &str) -> ArtifactCapability {
    ArtifactCapability::Unsupported {
        reason: reason(&format!("provider.unsupported-{family}")),
    }
}

fn direct_http_capabilities() -> WebArtifactCapabilitySet {
    WebArtifactCapabilitySet::new(
        supported(ArtifactMultiplicity::Many),
        unsupported("rendered-dom"),
        unsupported("accessibility-tree"),
        supported(ArtifactMultiplicity::ExactlyOne),
        supported(ArtifactMultiplicity::ExactlyOne),
        unsupported("storage"),
        unsupported("layout"),
        unsupported("visual"),
        unsupported("runtime-diagnostics"),
    )
}

const fn browser_capabilities() -> WebArtifactCapabilitySet {
    WebArtifactCapabilitySet::new(
        supported(ArtifactMultiplicity::Many),
        supported(ArtifactMultiplicity::Many),
        supported(ArtifactMultiplicity::Many),
        supported(ArtifactMultiplicity::Many),
        supported(ArtifactMultiplicity::Many),
        supported(ArtifactMultiplicity::Many),
        supported(ArtifactMultiplicity::Many),
        supported(ArtifactMultiplicity::Many),
        supported(ArtifactMultiplicity::ExactlyOne),
    )
}

#[test]
fn direct_http_support_does_not_imply_browser_artifacts() {
    let profile = WebProviderCapabilityProfile::new(
        producer("com.cascadinglabs.wreq-adapter"),
        AcquisitionCapabilityProfile::DirectHttp,
        direct_http_capabilities(),
    )
    .unwrap();

    assert!(matches!(
        profile.artifacts().source(),
        ArtifactCapability::Supported { .. }
    ));
    assert!(matches!(
        profile.artifacts().rendered_dom(),
        ArtifactCapability::Unsupported { .. }
    ));
    assert!(matches!(
        profile.artifacts().runtime_diagnostics(),
        ArtifactCapability::Unsupported { .. }
    ));

    let encoded = serde_json::to_value(&profile).unwrap();
    assert_eq!(encoded["acquisition"]["kind"], json!("direct_http"));
    assert_eq!(
        serde_json::from_value::<WebProviderCapabilityProfile>(encoded).unwrap(),
        profile
    );
}

#[test]
fn headless_and_headful_are_browser_configuration_not_provider_kinds() {
    let headless = WebProviderCapabilityProfile::new(
        producer("com.cascadinglabs.browser-adapter"),
        AcquisitionCapabilityProfile::DocumentNavigation(BrowserNavigationCapabilityProfile::new(
            BrowserMode::Headless,
        )),
        browser_capabilities(),
    )
    .unwrap();
    let headful = WebProviderCapabilityProfile::new(
        producer("com.cascadinglabs.browser-adapter"),
        AcquisitionCapabilityProfile::DocumentNavigation(BrowserNavigationCapabilityProfile::new(
            BrowserMode::Headful,
        )),
        browser_capabilities(),
    )
    .unwrap();

    let headless_json = serde_json::to_value(&headless).unwrap();
    let headful_json = serde_json::to_value(&headful).unwrap();
    assert_eq!(
        headless_json["acquisition"]["kind"],
        json!("document_navigation")
    );
    assert_eq!(
        headful_json["acquisition"]["kind"],
        json!("document_navigation")
    );
    assert_eq!(
        headless_json["acquisition"]["configuration"]["mode"],
        json!("headless")
    );
    assert_eq!(
        headful_json["acquisition"]["configuration"]["mode"],
        json!("headful")
    );
    assert_ne!(headless, headful);
}

#[test]
fn capability_sets_are_exhaustive_on_the_wire() {
    let profile = WebProviderCapabilityProfile::new(
        producer("com.cascadinglabs.browser-adapter"),
        AcquisitionCapabilityProfile::DocumentNavigation(BrowserNavigationCapabilityProfile::new(
            BrowserMode::Headless,
        )),
        browser_capabilities(),
    )
    .unwrap();
    let mut encoded = serde_json::to_value(profile).unwrap();
    encoded["artifacts"]
        .as_object_mut()
        .unwrap()
        .remove("runtime_diagnostics");

    assert!(serde_json::from_value::<WebProviderCapabilityProfile>(encoded).is_err());
}

#[test]
fn non_browser_profiles_reject_browser_only_capabilities() {
    let result = WebProviderCapabilityProfile::new(
        producer("com.cascadinglabs.wreq-adapter"),
        AcquisitionCapabilityProfile::DirectHttp,
        browser_capabilities(),
    );

    assert_eq!(
        result,
        Err(
            WebProviderCapabilityProfileError::BrowserArtifactOnHttpProfile {
                family: WebArtifactFamily::RenderedDom,
            }
        )
    );

    let browser = WebProviderCapabilityProfile::new(
        producer("com.cascadinglabs.browser-adapter"),
        AcquisitionCapabilityProfile::DocumentNavigation(BrowserNavigationCapabilityProfile::new(
            BrowserMode::Headless,
        )),
        browser_capabilities(),
    )
    .unwrap();
    let mut encoded = serde_json::to_value(browser).unwrap();
    encoded["acquisition"] = json!({ "kind": "direct_http" });
    assert!(serde_json::from_value::<WebProviderCapabilityProfile>(encoded).is_err());
}
