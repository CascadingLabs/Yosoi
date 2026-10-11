use std::collections::HashMap;

use crate::internal::web_capture::{
    BrowserArtifactStaging, BrowserStagingParts, BrowserStructuredEvidence, CaptureResolution,
    HttpRedirectStatus, LossExtent, Observation, ObservedWebOrigin, RedirectCause, RedirectHop,
    ResolvedBrowserCaptureSpec,
};

use super::BrowserFinalizationError;

pub(super) fn derive_resolution(
    spec: &ResolvedBrowserCaptureSpec,
    staging: &BrowserArtifactStaging,
    resource_origin: Observation<ObservedWebOrigin>,
    initiator_origin: Observation<ObservedWebOrigin>,
) -> Result<CaptureResolution, BrowserFinalizationError> {
    let mut observed_final_url = Observation::Unobserved;
    let mut observed_redirects = Observation::Unobserved;
    for slot in staging.slots() {
        let BrowserStagingParts::Structured {
            evidence:
                BrowserStructuredEvidence::Network {
                    requested_url,
                    final_url,
                    resources,
                    redirects,
                    resource_accounting,
                    ..
                },
            ..
        } = slot.outcome().parts()
        else {
            continue;
        };
        if requested_url.as_ref().is_some_and(|observed| {
            !observed.same_network_resource_as(&spec.request().target().as_resolved())
        }) {
            return Err(BrowserFinalizationError::ResolutionMismatch);
        }
        observed_final_url = final_url.as_ref().map_or(Observation::Unobserved, |url| {
            Observation::Observed(url.clone())
        });
        if resource_accounting.lost() == LossExtent::Known(0) {
            let urls = resources
                .iter()
                .map(|resource| (resource.id, resource.url.as_ref()))
                .collect::<HashMap<_, _>>();
            let mut chain = Vec::with_capacity(redirects.len());
            let mut urls_complete = true;
            for edge in redirects {
                let (Some(from), Some(to)) = (
                    urls.get(&edge.from).and_then(|url| *url),
                    urls.get(&edge.to).and_then(|url| *url),
                ) else {
                    urls_complete = false;
                    break;
                };
                let cause = match edge.status {
                    Some(status) => RedirectCause::Http(
                        HttpRedirectStatus::try_from(status)
                            .map_err(|_| BrowserFinalizationError::ResolutionMismatch)?,
                    ),
                    None => RedirectCause::Other,
                };
                chain.push(RedirectHop::new(from.clone(), to.clone(), cause));
            }
            if urls_complete {
                observed_redirects = Observation::Observed(chain);
            }
        }
    }
    CaptureResolution::new(
        observed_final_url,
        observed_redirects,
        resource_origin,
        initiator_origin,
    )
    .map_err(|_| BrowserFinalizationError::ResolutionMismatch)
}
