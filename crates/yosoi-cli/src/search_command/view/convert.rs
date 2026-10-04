use std::num::NonZeroU16;

use yosoi_engine::{
    policy::ProviderDefaultsVersion,
    search::{
        FeatureCoverage, ProviderCharge, ProviderOutcome, ProviderResult, RequestAttemptTerminal,
        SearchFeature, SearchHit, SearchIssue, SearchResponse, SearchResultUrl, WebCoverage,
    },
};

use super::names::{
    attempt_diagnostic_name, defaults_status_name, failure_name, issue_name, provider_name,
    termination_name, unavailable_name,
};
use super::{
    ChargeView, CoverageView, FeatureView, HitView, ImageView, IssueView, LocalPlaceView,
    ProviderIdentityView, ProviderProfileView, ProviderStatus, ProviderView, RequestAttemptView,
    SearchEnvelope,
};

impl<'a> SearchEnvelope<'a> {
    pub(in crate::search_command) fn from_response(
        response: &'a SearchResponse,
        policy_profile: Option<&'a str>,
    ) -> Self {
        Self {
            schema_version: 2,
            cli_version: env!("CARGO_PKG_VERSION"),
            policy_profile,
            policy_identity: response.policy_identity().into(),
            termination: termination_name(response.termination()),
            providers: response
                .providers()
                .iter()
                .map(ProviderView::from_result)
                .collect(),
        }
    }
}

impl<'a> FeatureView<'a> {
    pub(super) fn from_feature(feature: &'a SearchFeature) -> Self {
        match feature {
            SearchFeature::Sponsored {
                placement_index,
                destination,
                label,
            } => Self::Sponsored {
                placement_index: placement_index.get(),
                destination: destination.as_str(),
                label: label.as_deref(),
            },
            SearchFeature::Answer {
                placement_index,
                text,
                citations,
            } => Self::Answer {
                placement_index: placement_index.get(),
                text,
                citations: citations.iter().map(SearchResultUrl::as_str).collect(),
            },
            SearchFeature::ImageGallery {
                placement_index,
                images,
            } => Self::ImageGallery {
                placement_index: placement_index.get(),
                images: images
                    .iter()
                    .map(|image| ImageView {
                        image_url: image.image_url.as_str(),
                        source_page_url: image.source_page_url.as_str(),
                    })
                    .collect(),
            },
            SearchFeature::LocalPack {
                placement_index,
                places,
                map_url,
            } => Self::LocalPack {
                placement_index: placement_index.get(),
                places: places
                    .iter()
                    .map(|place| LocalPlaceView {
                        name: &place.name,
                        place_url: place.place_url.as_str(),
                    })
                    .collect(),
                map_url: map_url.as_ref().map(SearchResultUrl::as_str),
            },
        }
    }

    pub(in crate::search_command) const fn label(&self) -> &'static str {
        match self {
            Self::Sponsored { .. } => "sponsored",
            Self::Answer { .. } => "answer",
            Self::ImageGallery { .. } => "image gallery",
            Self::LocalPack { .. } => "local pack",
        }
    }
}

impl<'a> ProviderView<'a> {
    pub(super) fn from_result(result: &'a ProviderResult) -> Self {
        let (status, coverage, detail, hits, features, issues) = match result.outcome() {
            ProviderOutcome::Results(page) => (
                ProviderStatus::Results,
                Some(CoverageView {
                    web: match page.coverage().web() {
                        WebCoverage::Complete => "complete",
                        WebCoverage::Partial => "partial",
                    },
                    rich_features: match page.coverage().rich_features() {
                        FeatureCoverage::NotCollected => "not_collected",
                        FeatureCoverage::Collected => "collected",
                        FeatureCoverage::Partial => "partial",
                    },
                }),
                None,
                page.hits().iter().map(HitView::from_hit).collect(),
                page.features()
                    .iter()
                    .map(FeatureView::from_feature)
                    .collect(),
                page.issues().iter().map(IssueView::from_issue).collect(),
            ),
            ProviderOutcome::Empty => (
                ProviderStatus::Empty,
                None,
                None,
                Vec::new(),
                Vec::new(),
                Vec::new(),
            ),
            ProviderOutcome::Failed(failure) => (
                ProviderStatus::Failed,
                None,
                Some(failure_name(*failure)),
                Vec::new(),
                Vec::new(),
                Vec::new(),
            ),
            ProviderOutcome::Cancelled => (
                ProviderStatus::Cancelled,
                None,
                None,
                Vec::new(),
                Vec::new(),
                Vec::new(),
            ),
            ProviderOutcome::NotStarted(reason) => (
                ProviderStatus::NotStarted,
                None,
                Some(unavailable_name(*reason)),
                Vec::new(),
                Vec::new(),
                Vec::new(),
            ),
        };
        let identity = result.identity();
        let profile = result.profile();
        Self {
            provider: provider_name(result.provider()),
            identity: ProviderIdentityView {
                endpoint: identity.endpoint,
                adapter_version: identity.adapter_version,
                parser_version: identity.parser_version,
            },
            status,
            coverage,
            detail,
            profile: ProviderProfileView {
                acquisition: profile.acquisition,
                defaults_status: defaults_status_name(profile.defaults_status),
                defaults_version: profile.defaults_version.map(ProviderDefaultsVersion::get),
                effective_request_policy: profile.effective_request_policy.map(Into::into),
            },
            request_id: result.request_id().map(|id| id.to_string()),
            recovery_query: result.recovery_query(),
            attempts: result
                .attempts()
                .iter()
                .map(|attempt| RequestAttemptView {
                    request_id: attempt.request_id.to_string(),
                    capture_id: attempt.capture_id.to_string(),
                    acquisition: attempt.acquisition,
                    http_status: attempt.http_status,
                    source_bytes: attempt.source_bytes,
                    diagnostic: attempt.diagnostic.map(attempt_diagnostic_name),
                    terminal: match attempt.terminal {
                        RequestAttemptTerminal::Completed => "completed",
                        RequestAttemptTerminal::Failed => "failed",
                        RequestAttemptTerminal::NotStarted => "not_started",
                    },
                })
                .collect(),
            hits,
            features,
            applied_filters: Vec::new(),
            issues,
            cost: ChargeView::from_charge(result.charge()),
        }
    }
}

impl<'a> HitView<'a> {
    pub(super) fn from_hit(hit: &'a SearchHit) -> Self {
        Self {
            organic_rank: hit.organic_rank().get(),
            placement_index: hit.placement_index().get(),
            url: hit.url().as_str(),
            title: hit.title(),
            snippet: hit.snippet(),
            display_url: hit.display_url(),
            publisher: hit.publisher(),
            published_at: hit.published_at(),
            thumbnail_url: hit.thumbnail_url().map(SearchResultUrl::as_str),
        }
    }
}

impl IssueView {
    pub(super) fn from_issue(issue: &SearchIssue) -> Self {
        Self {
            placement_index: issue.placement_index.map(NonZeroU16::get),
            kind: issue_name(issue.kind),
        }
    }
}

impl<'a> ChargeView<'a> {
    pub(super) fn from_charge(charge: &'a ProviderCharge) -> Self {
        match charge {
            ProviderCharge::Unknown => Self {
                status: "unknown",
                currency: None,
                amount: None,
            },
            ProviderCharge::Known { currency, amount } => Self {
                status: "known",
                currency: Some(currency),
                amount: Some(amount),
            },
        }
    }
}
