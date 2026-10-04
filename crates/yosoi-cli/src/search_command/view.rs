use serde::Serialize;
use yosoi::{EffectivePolicyIdentity, policy::AcquisitionKind};

mod convert;
pub(super) mod names;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum ProviderStatus {
    Results,
    Empty,
    Failed,
    Cancelled,
    NotStarted,
}

impl ProviderStatus {
    pub(super) const fn is_valid(self) -> bool {
        matches!(self, Self::Results | Self::Empty)
    }

    pub(super) const fn label(self) -> &'static str {
        match self {
            Self::Results => "results",
            Self::Empty => "empty",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
            Self::NotStarted => "not_started",
        }
    }
}

#[derive(Debug, Serialize)]
pub(super) struct PolicyIdentityView {
    pub(super) version: u16,
    pub(super) digest: String,
}

impl From<EffectivePolicyIdentity> for PolicyIdentityView {
    fn from(identity: EffectivePolicyIdentity) -> Self {
        Self {
            version: identity.version(),
            digest: identity.digest().to_string(),
        }
    }
}

#[derive(Debug, Serialize)]
pub(super) struct SearchEnvelope<'a> {
    pub(super) schema_version: u16,
    pub(super) cli_version: &'static str,
    pub(super) policy_profile: Option<&'a str>,
    pub(super) policy_identity: PolicyIdentityView,
    pub(super) termination: &'static str,
    pub(super) providers: Vec<ProviderView<'a>>,
}

#[derive(Debug, Serialize)]
pub(super) struct ProviderIdentityView<'a> {
    pub(super) endpoint: Option<&'a str>,
    pub(super) adapter_version: Option<&'a str>,
    pub(super) parser_version: Option<&'a str>,
}

#[derive(Debug, Serialize)]
pub(super) struct ProviderProfileView {
    pub(super) acquisition: Option<AcquisitionKind>,
    pub(super) defaults_status: &'static str,
    pub(super) defaults_version: Option<u16>,
    pub(super) effective_request_policy: Option<PolicyIdentityView>,
}

#[derive(Debug, Serialize)]
pub(super) struct HitView<'a> {
    pub(super) organic_rank: u16,
    pub(super) placement_index: u16,
    pub(super) url: &'a str,
    pub(super) title: Option<&'a str>,
    pub(super) snippet: Option<&'a str>,
    pub(super) display_url: Option<&'a str>,
    pub(super) publisher: Option<&'a str>,
    pub(super) published_at: Option<&'a str>,
    pub(super) thumbnail_url: Option<&'a str>,
}

#[derive(Debug, Serialize)]
pub(super) struct IssueView {
    pub(super) placement_index: Option<u16>,
    pub(super) kind: &'static str,
}

#[derive(Debug, Serialize)]
pub(super) struct ChargeView<'a> {
    pub(super) status: &'static str,
    pub(super) currency: Option<&'a str>,
    pub(super) amount: Option<&'a str>,
}

#[derive(Debug, Serialize)]
pub(super) struct CoverageView {
    pub(super) web: &'static str,
    pub(super) rich_features: &'static str,
}

#[derive(Debug, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub(super) enum FeatureView<'a> {
    Sponsored {
        placement_index: u16,
        destination: &'a str,
        label: Option<&'a str>,
    },
    Answer {
        placement_index: u16,
        text: &'a str,
        citations: Vec<&'a str>,
    },
    ImageGallery {
        placement_index: u16,
        images: Vec<ImageView<'a>>,
    },
    LocalPack {
        placement_index: u16,
        places: Vec<LocalPlaceView<'a>>,
        map_url: Option<&'a str>,
    },
}

#[derive(Debug, Serialize)]
pub(super) struct ImageView<'a> {
    pub(super) image_url: &'a str,
    pub(super) source_page_url: &'a str,
}

#[derive(Debug, Serialize)]
pub(super) struct LocalPlaceView<'a> {
    pub(super) name: &'a str,
    pub(super) place_url: &'a str,
}

#[derive(Debug, Serialize)]
pub(super) struct RequestAttemptView {
    pub(super) request_id: String,
    pub(super) capture_id: String,
    pub(super) acquisition: AcquisitionKind,
    pub(super) http_status: Option<u16>,
    pub(super) source_bytes: Option<u64>,
    pub(super) diagnostic: Option<&'static str>,
    pub(super) terminal: &'static str,
}

#[derive(Debug, Serialize)]
pub(super) struct ProviderView<'a> {
    pub(super) provider: &'static str,
    pub(super) identity: ProviderIdentityView<'a>,
    pub(super) status: ProviderStatus,
    pub(super) coverage: Option<CoverageView>,
    pub(super) detail: Option<&'static str>,
    pub(super) profile: ProviderProfileView,
    pub(super) request_id: Option<String>,
    pub(super) recovery_query: Option<&'a str>,
    pub(super) attempts: Vec<RequestAttemptView>,
    pub(super) hits: Vec<HitView<'a>>,
    pub(super) features: Vec<FeatureView<'a>>,
    pub(super) applied_filters: Vec<&'static str>,
    pub(super) issues: Vec<IssueView>,
    pub(super) cost: ChargeView<'a>,
}
