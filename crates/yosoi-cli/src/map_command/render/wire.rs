use serde::{Serialize, Serializer, ser::SerializeStruct};
use yosoi_engine::map;

pub(super) struct StatusView<'a> {
    status: &'static str,
    detail: Option<StatusDetail<'a>>,
}

enum StatusDetail<'a> {
    Reason(&'static str),
    Failure(&'a map::SourceFailure),
}

impl<'a> StatusView<'a> {
    pub(super) const fn plain(status: &'static str) -> Self {
        Self {
            status,
            detail: None,
        }
    }

    pub(super) const fn reason(status: &'static str, reason: &'static str) -> Self {
        Self {
            status,
            detail: Some(StatusDetail::Reason(reason)),
        }
    }

    pub(super) const fn failure(status: &'static str, failure: &'a map::SourceFailure) -> Self {
        Self {
            status,
            detail: Some(StatusDetail::Failure(failure)),
        }
    }
}

impl Serialize for StatusView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state =
            serializer.serialize_struct("Status", if self.detail.is_some() { 2 } else { 1 })?;
        state.serialize_field("status", self.status)?;
        match &self.detail {
            Some(StatusDetail::Reason(reason)) => state.serialize_field("reason", reason)?,
            Some(StatusDetail::Failure(failure)) => {
                state.serialize_field("failure", &FailureView(failure))?;
            }
            None => {}
        }
        state.end()
    }
}

pub(super) struct FailureView<'a>(&'a map::SourceFailure);

impl Serialize for FailureView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let (kind, http_status) = source_failure_fields(self.0);
        let mut state =
            serializer.serialize_struct("Failure", if http_status.is_some() { 2 } else { 1 })?;
        state.serialize_field("kind", kind)?;
        if let Some(status) = http_status {
            state.serialize_field("http_status", &status)?;
        }
        state.end()
    }
}

const fn source_failure_fields(failure: &map::SourceFailure) -> (&'static str, Option<u16>) {
    match failure {
        map::SourceFailure::Transport => ("transport", None),
        map::SourceFailure::HttpStatus(status) => ("http_status", Some(*status)),
        map::SourceFailure::Parse => ("parse", None),
        map::SourceFailure::IncompleteDocument => ("incomplete_document", None),
        map::SourceFailure::RedirectRejected => ("redirect_rejected", None),
        map::SourceFailure::RedirectLimit => ("redirect_limit", None),
        map::SourceFailure::RetentionLimit => ("retention_limit", None),
        map::SourceFailure::RequestDeadline => ("request_deadline", None),
        map::SourceFailure::RateLimited => ("rate_limited", None),
        map::SourceFailure::UnexpectedSitemapContent => ("unexpected_sitemap_content", None),
    }
}

pub(super) fn source_failure_label(failure: &map::SourceFailure) -> String {
    match failure {
        map::SourceFailure::Transport => "transport".to_owned(),
        map::SourceFailure::HttpStatus(400) => "http 400 bad request".to_owned(),
        map::SourceFailure::HttpStatus(502) => {
            "http 502 bad gateway (gateway/upstream service failure)".to_owned()
        }
        map::SourceFailure::HttpStatus(status) => format!("http status {status}"),
        map::SourceFailure::Parse => "parse".to_owned(),
        map::SourceFailure::IncompleteDocument => "incomplete document".to_owned(),
        map::SourceFailure::RedirectRejected => "redirect rejected".to_owned(),
        map::SourceFailure::RedirectLimit => "redirect limit".to_owned(),
        map::SourceFailure::RetentionLimit => "retention limit".to_owned(),
        map::SourceFailure::RequestDeadline => "request deadline exceeded".to_owned(),
        map::SourceFailure::RateLimited => "public provider quota reached".to_owned(),
        map::SourceFailure::UnexpectedSitemapContent => {
            "expected sitemap XML, received HTML".to_owned()
        }
    }
}

pub(super) const fn discovery_source_label(source: map::DiscoverySource) -> &'static str {
    match source {
        map::DiscoverySource::Seed => "seed",
        map::DiscoverySource::HtmlLink => "html_link",
        map::DiscoverySource::XmlLink => "xml_link",
        map::DiscoverySource::PassiveProvider(provider) => provider.name(),
        map::DiscoverySource::Sitemap => "sitemap",
        map::DiscoverySource::Robots => "robots",
        map::DiscoverySource::Redirect => "redirect",
        map::DiscoverySource::PassiveCertificate => "passive_certificate",
    }
}

pub(super) const fn host_verification_label(verification: map::HostVerification) -> &'static str {
    match verification {
        map::HostVerification::Unverified => "unverified",
        map::HostVerification::HttpObserved => "http_observed",
    }
}

pub(super) const fn relationship_kind_label(kind: map::RelationshipKind) -> &'static str {
    match kind {
        map::RelationshipKind::Link => "link",
        map::RelationshipKind::Redirect => "redirect",
        map::RelationshipKind::Canonical => "canonical",
    }
}

pub(super) const fn skip_reason_label(reason: map::SkipReason) -> &'static str {
    match reason {
        map::SkipReason::Depth => "depth",
        map::SkipReason::Robots => "robots",
        map::SkipReason::NonHtml => "non_html",
        map::SkipReason::Budget => "budget",
    }
}

pub(super) const fn pending_reason_label(reason: map::PendingReason) -> &'static str {
    match reason {
        map::PendingReason::AwaitingExploration => "awaiting_exploration",
        map::PendingReason::DepthBoundary => "depth_boundary",
        map::PendingReason::OperationStopped => "operation_stopped",
        map::PendingReason::ProbeCandidate => "probe_candidate",
    }
}

pub(super) const fn support_document_label(kind: map::SupportDocumentKind) -> &'static str {
    match kind {
        map::SupportDocumentKind::Robots => "robots",
        map::SupportDocumentKind::Sitemap => "sitemap",
        map::SupportDocumentKind::SitemapIndex => "sitemap_index",
    }
}

pub(super) const fn limit_label(limit: map::LimitReached) -> &'static str {
    match limit {
        map::LimitReached::Hosts => "hosts",
        map::LimitReached::Urls => "urls",
        map::LimitReached::Relationships => "relationships",
        map::LimitReached::Observations => "observations",
        map::LimitReached::Pending => "pending",
        map::LimitReached::Requests => "requests",
        map::LimitReached::Sitemaps => "sitemaps",
        map::LimitReached::SitemapDepth => "sitemap_depth",
        map::LimitReached::ResponseBytes => "response_bytes",
        map::LimitReached::TotalResponseBytes => "total_response_bytes",
        map::LimitReached::InventoryBytes => "inventory_bytes",
        map::LimitReached::ParserEntries => "parser_entries",
    }
}

pub(super) const fn rejection_label(rejection: map::Rejection) -> &'static str {
    match rejection {
        map::Rejection::InvalidUrl => "invalid_url",
        map::Rejection::UnsupportedScheme => "unsupported_scheme",
        map::Rejection::Credentials => "credentials",
        map::Rejection::HostScope => "host_scope",
        map::Rejection::OriginScope => "origin_scope",
        map::Rejection::PathScope => "path_scope",
        map::Rejection::Filtered => "filtered",
        map::Rejection::UrlLength => "url_length",
        map::Rejection::InvalidHost => "invalid_host",
        map::Rejection::UnsupportedDomainScope => "unsupported_domain_scope",
        map::Rejection::HostnameLength => "hostname_length",
    }
}

pub(super) const fn reason_label(reason: map::OmissionReason) -> &'static str {
    match reason {
        map::OmissionReason::Admission(_) => "admission",
        map::OmissionReason::Robots => "robots",
        map::OmissionReason::Depth => "depth",
        map::OmissionReason::SitemapDepth => "sitemap_depth",
        map::OmissionReason::Pending => "pending",
        map::OmissionReason::Inventory => "inventory",
        map::OmissionReason::Retention => "retention",
        map::OmissionReason::Wildcard => "wildcard",
        map::OmissionReason::Other => "other",
    }
}

pub(super) fn termination_label(termination: map::MapTermination) -> String {
    match termination {
        map::MapTermination::Exhausted => "exhausted".to_owned(),
        map::MapTermination::Limit(limit) => format!("limit_reached ({})", limit_label(limit)),
        map::MapTermination::Deadline => "deadline".to_owned(),
        map::MapTermination::Cancelled => "cancelled".to_owned(),
    }
}

pub(super) struct TerminationView(pub(super) map::MapTermination);

impl Serialize for TerminationView {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let fields = if matches!(self.0, map::MapTermination::Limit(_)) {
            2
        } else {
            1
        };
        let mut state = serializer.serialize_struct("Termination", fields)?;
        match self.0 {
            map::MapTermination::Exhausted => state.serialize_field("status", "exhausted")?,
            map::MapTermination::Limit(limit) => {
                state.serialize_field("status", "limit")?;
                state.serialize_field("limit", limit_label(limit))?;
            }
            map::MapTermination::Deadline => state.serialize_field("status", "deadline")?,
            map::MapTermination::Cancelled => state.serialize_field("status", "cancelled")?,
        }
        state.end()
    }
}
