use crate::internal::web_capture as yosoi_web_capture;

use crate::internal::direct_http::{
    DirectHttpContentLimits, DirectHttpOutputSchemas, DirectHttpRedirectPolicy,
    DirectHttpRedirectTargetPolicy, RedirectHopLimit, ResolvedDirectHttpCaptureSpec,
    SourceRetentionPolicy,
};
use crate::internal::web_capture::{
    ArtifactRequest, DirectHttpAcquisition, DirectHttpTransportProfile, ObservationLimits,
    ObservationPolicy, SettlementPolicy, WebAcquisitionStrategy, WebArtifactRequestSet,
};

use crate::internal::engine::{
    EffectivePolicy, EffectivePolicyIdentity, PreparedAttempt,
    policy::{
        AcquisitionKind, DirectHttpRedirectTargets, DirectHttpRedirects, DocumentRequest, Request,
    },
};

use super::{
    AppliedPolicy, AppliedPolicyLimit, PolicyDecision, PolicyResolutionError, ResolvedPolicySpec,
    applied_decisions, inputs::DirectHttpResolutionInputs,
};

pub(super) fn resolve(
    identity: EffectivePolicyIdentity,
    policy: &EffectivePolicy,
    attempt: &PreparedAttempt,
    inputs: DirectHttpResolutionInputs,
) -> Result<super::ResolvedPolicyAttempt, PolicyResolutionError> {
    ensure_supported_acquisition(&inputs.acquisition)?;
    ensure_supported_documents(attempt)?;

    let policy_request = &policy.request;
    let mut decisions = applied_decisions(attempt);

    let (redirects, redirect_targets) = resolve_redirects(policy_request)?;
    decisions.push(PolicyDecision::DirectHttpRedirects { policy: redirects });
    if let DirectHttpRedirects::Follow { .. } = policy_request.direct_http_redirects {
        decisions.push(PolicyDecision::DirectHttpRedirectTargets {
            policy: redirect_targets,
        });
    }

    let request_value = super::capture_request(
        attempt,
        WebAcquisitionStrategy::DirectHttp(inputs.acquisition),
    );
    let observation = ObservationPolicy::new(
        ObservationLimits::new(
            policy_request
                .maximum_elapsed
                .to_capture_deadline()
                .map_err(PolicyResolutionError::DeadlineConversion)?,
            None,
            None,
        ),
        SettlementPolicy::Disabled,
    );
    let source_limits = DirectHttpContentLimits::new(
        policy_request.source.content_coded_bytes.to_byte_limit()?,
        policy_request.source.representation_bytes.to_byte_limit()?,
        policy_request.source.unicode_utf8_bytes.to_byte_limit()?,
    );
    let output_schemas = direct_output_schemas(&inputs.output_schemas, inputs.retention);
    let artifacts = WebArtifactRequestSet::new(
        ArtifactRequest::Required,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
    );
    let spec = ResolvedDirectHttpCaptureSpec::new(
        request_value,
        artifacts,
        observation,
        source_limits,
        redirects,
        inputs.accepted_formats,
        inputs.unsupported_format,
        inputs.retention,
        inputs.producer,
        inputs.operation,
        output_schemas,
    )?;

    let limits = vec![
        AppliedPolicyLimit::MaximumElapsed {
            microseconds: policy_request.maximum_elapsed.as_microseconds(),
        },
        AppliedPolicyLimit::DirectHttpSourceBytes {
            limits: source_limits,
        },
    ];

    Ok(super::ResolvedPolicyAttempt::new(
        ResolvedPolicySpec::DirectHttp {
            spec: Box::new(spec),
            redirect_targets,
        },
        AppliedPolicy::new(identity, decisions, limits),
    ))
}

const fn ensure_supported_acquisition(
    acquisition: &DirectHttpAcquisition,
) -> Result<(), PolicyResolutionError> {
    if !matches!(
        acquisition.transport_profile(),
        DirectHttpTransportProfile::Standard
    ) {
        return Err(PolicyResolutionError::UnsupportedDirectHttpProfile);
    }
    if !matches!(
        acquisition.session(),
        yosoi_web_capture::HttpSessionUse::Isolated
    ) {
        return Err(PolicyResolutionError::UnsupportedDirectHttpSession);
    }
    Ok(())
}

fn ensure_supported_documents(attempt: &PreparedAttempt) -> Result<(), PolicyResolutionError> {
    for document in attempt.documents() {
        if *document != DocumentRequest::ResponseDocument {
            return Err(PolicyResolutionError::UnsupportedDocument {
                acquisition: AcquisitionKind::DirectHttp,
                document: *document,
            });
        }
    }
    Ok(())
}

fn resolve_redirects(
    request: &Request,
) -> Result<(DirectHttpRedirectPolicy, DirectHttpRedirectTargetPolicy), PolicyResolutionError> {
    let redirects = match request.direct_http_redirects {
        DirectHttpRedirects::Disabled => DirectHttpRedirectPolicy::Disabled,
        DirectHttpRedirects::Follow { max_hops, .. } => {
            let max_hops = RedirectHopLimit::try_from(max_hops.get())?;
            DirectHttpRedirectPolicy::follow(max_hops)
        }
    };
    let targets = match request.direct_http_redirects {
        DirectHttpRedirects::Disabled
        | DirectHttpRedirects::Follow {
            targets: DirectHttpRedirectTargets::AllowHttpAndHttps,
            ..
        } => DirectHttpRedirectTargetPolicy::AllowHttpAndHttps,
        DirectHttpRedirects::Follow {
            targets: DirectHttpRedirectTargets::SameOrigin,
            ..
        } => DirectHttpRedirectTargetPolicy::SameOrigin,
    };
    Ok((redirects, targets))
}

fn direct_output_schemas(
    candidates: &DirectHttpOutputSchemas,
    retention: SourceRetentionPolicy,
) -> DirectHttpOutputSchemas {
    let unicode_view = match retention {
        SourceRetentionPolicy::Representation => None,
        SourceRetentionPolicy::RepresentationAndUnicodeView => candidates.unicode_view().cloned(),
    };
    DirectHttpOutputSchemas::new(
        candidates.source().clone(),
        candidates.source_representation().clone(),
        None,
        unicode_view,
    )
}
