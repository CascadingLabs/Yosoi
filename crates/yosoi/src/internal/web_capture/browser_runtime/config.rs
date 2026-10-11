use crate::internal::browser as provider;
use crate::internal::web_capture as yosoi;
use crate::internal::web_capture::VoidCrawlAdapterError;

fn requested(request: yosoi::ArtifactRequest) -> bool {
    request != yosoi::ArtifactRequest::NotRequested
}

const fn validate_completion(
    completion: yosoi::NavigationCompletionPolicy,
) -> Result<(), VoidCrawlAdapterError> {
    if !matches!(
        completion,
        yosoi::NavigationCompletionPolicy::DomContentLoaded
            | yosoi::NavigationCompletionPolicy::ControllerCompleted
    ) {
        return Err(VoidCrawlAdapterError::UnsupportedNavigationPolicy);
    }
    Ok(())
}

fn validate_artifacts(
    artifacts: &yosoi::WebArtifactRequestSet,
) -> Result<(), VoidCrawlAdapterError> {
    for (family, request) in [
        (yosoi::WebArtifactFamily::Cookies, artifacts.cookies()),
        (yosoi::WebArtifactFamily::Storage, artifacts.storage()),
    ] {
        if requested(request) {
            return Err(VoidCrawlAdapterError::UnsupportedFamily { family });
        }
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct InstrumentationNeeds {
    pub network: bool,
    pub runtime: bool,
}

pub fn instrumentation_needs(spec: &yosoi::ResolvedBrowserCaptureSpec) -> InstrumentationNeeds {
    let artifacts = spec.artifacts();
    InstrumentationNeeds {
        network: requested(artifacts.source())
            || requested(artifacts.network())
            || matches!(
                spec.observation().settlement(),
                yosoi::SettlementPolicy::QuietPeriod(_)
            ),
        runtime: requested(artifacts.runtime_diagnostics()),
    }
}

const fn validate_instrumentation(
    instrumentation: yosoi::BrowserInstrumentationMode,
    needs: InstrumentationNeeds,
) -> Result<(), VoidCrawlAdapterError> {
    let exact = match instrumentation {
        yosoi::BrowserInstrumentationMode::Normal => true,
        yosoi::BrowserInstrumentationMode::Minimal => !needs.network && !needs.runtime,
        yosoi::BrowserInstrumentationMode::MinimalNetworkEscalated => {
            needs.network && !needs.runtime
        }
        yosoi::BrowserInstrumentationMode::MinimalRuntimeEscalated => {
            !needs.network && needs.runtime
        }
        yosoi::BrowserInstrumentationMode::MinimalBothEscalated => needs.network && needs.runtime,
    };
    if exact {
        Ok(())
    } else {
        Err(VoidCrawlAdapterError::CapabilityMismatch)
    }
}

pub fn validate(spec: &yosoi::ResolvedBrowserCaptureSpec) -> Result<(), VoidCrawlAdapterError> {
    if spec.environment().isolation() != yosoi::FreshBrowserIsolation::FreshIsolatedContext {
        return Err(VoidCrawlAdapterError::UnsupportedIsolation);
    }
    validate_completion(spec.navigation_policy().completion())?;
    let artifacts = spec.artifacts();
    validate_artifacts(&artifacts)?;
    validate_instrumentation(
        spec.capabilities().instrumentation(),
        instrumentation_needs(spec),
    )
}

pub const fn cdp_mode(spec: &yosoi::ResolvedBrowserCaptureSpec) -> provider::CdpMode {
    match spec.capabilities().instrumentation() {
        yosoi::BrowserInstrumentationMode::Normal => provider::CdpMode::Normal,
        yosoi::BrowserInstrumentationMode::Minimal
        | yosoi::BrowserInstrumentationMode::MinimalNetworkEscalated
        | yosoi::BrowserInstrumentationMode::MinimalRuntimeEscalated
        | yosoi::BrowserInstrumentationMode::MinimalBothEscalated => provider::CdpMode::Minimal,
    }
}

pub fn byte_limit(
    spec: &yosoi::ResolvedBrowserCaptureSpec,
    domain: yosoi::BrowserByteDomain,
) -> Result<usize, VoidCrawlAdapterError> {
    let bound = spec
        .bounds()
        .byte_bounds()
        .iter()
        .find(|bound| bound.domain() == domain)
        .ok_or(VoidCrawlAdapterError::InvalidResolvedSpec)?;
    usize::try_from(bound.limit().get()).map_err(|_| VoidCrawlAdapterError::InvalidResolvedSpec)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn artifacts(requests: [yosoi::ArtifactRequest; 9]) -> yosoi::WebArtifactRequestSet {
        let [
            source,
            dom,
            ax,
            network,
            cookies,
            storage,
            layout,
            visual,
            runtime,
        ] = requests;
        yosoi::WebArtifactRequestSet::new(
            source, dom, ax, network, cookies, storage, layout, visual, runtime,
        )
    }

    #[test]
    fn completion_policy_is_closed() {
        for completion in [
            yosoi::NavigationCompletionPolicy::LoadEvent,
            yosoi::NavigationCompletionPolicy::NetworkIdle,
        ] {
            assert!(matches!(
                validate_completion(completion),
                Err(VoidCrawlAdapterError::UnsupportedNavigationPolicy)
            ));
        }
        assert!(validate_completion(yosoi::NavigationCompletionPolicy::DomContentLoaded).is_ok());
        assert!(
            validate_completion(yosoi::NavigationCompletionPolicy::ControllerCompleted).is_ok()
        );
    }

    #[test]
    fn artifact_subset_is_closed() {
        let no = yosoi::ArtifactRequest::NotRequested;
        let yes = yosoi::ArtifactRequest::Required;
        for supported_index in [1_usize, 2, 3, 6, 7, 8] {
            let mut requests = [no; 9];
            if let Some(request) = requests.get_mut(supported_index) {
                *request = yes;
            }
            assert!(validate_artifacts(&artifacts(requests)).is_ok());
        }
        for (unsupported_index, expected_family) in [
            (4, yosoi::WebArtifactFamily::Cookies),
            (5, yosoi::WebArtifactFamily::Storage),
        ] {
            let mut requests = [no; 9];
            if let Some(request) = requests.get_mut(unsupported_index) {
                *request = yes;
            }
            let error = validate_artifacts(&artifacts(requests)).unwrap_err();
            assert!(matches!(
                error,
                VoidCrawlAdapterError::UnsupportedFamily { family }
                    if family == expected_family
            ));
        }
    }

    #[test]
    fn instrumentation_modes_are_exact() {
        use crate::internal::web_capture::BrowserInstrumentationMode as Mode;
        let modes = [
            Mode::Minimal,
            Mode::MinimalNetworkEscalated,
            Mode::MinimalRuntimeEscalated,
            Mode::MinimalBothEscalated,
        ];
        for network in [false, true] {
            for runtime in [false, true] {
                let needs = InstrumentationNeeds { network, runtime };
                assert!(validate_instrumentation(Mode::Normal, needs).is_ok());
                let expected = match (network, runtime) {
                    (false, false) => Mode::Minimal,
                    (true, false) => Mode::MinimalNetworkEscalated,
                    (false, true) => Mode::MinimalRuntimeEscalated,
                    (true, true) => Mode::MinimalBothEscalated,
                };
                for mode in modes {
                    assert_eq!(
                        validate_instrumentation(mode, needs).is_ok(),
                        mode == expected
                    );
                }
            }
        }
    }
}
