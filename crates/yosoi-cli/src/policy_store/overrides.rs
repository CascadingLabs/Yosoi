//! Typed sparse overrides for public Yosoi policy fields.

use std::num::{NonZeroU16, NonZeroU32, NonZeroUsize};

use serde::{Deserialize, Serialize};
use yosoi_engine::{CountLimit, Policy, StepLimit, policy};

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PolicyOverrides {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub page: Option<PageOverrides>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub request: Option<RequestOverrides>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub documents: Option<DocumentOverrides>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub locators: Option<LocatorOverrides>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tuning: Option<policy::Tuning>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub map: Option<policy::Map>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub search: Option<SearchOverrides>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PageOverrides {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub acquisitions: Option<Vec<policy::Acquisition>>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RequestOverrides {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub maximum_elapsed: Option<policy::MaximumElapsed>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source: Option<SourceOverrides>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub browser: Option<BrowserOverrides>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub direct_http_redirects: Option<policy::DirectHttpRedirects>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
#[allow(clippy::struct_field_names)] // These serialized names mirror public request policy fields.
pub struct SourceOverrides {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub content_coded_bytes: Option<policy::AddressableByteLimit>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub representation_bytes: Option<policy::AddressableByteLimit>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unicode_utf8_bytes: Option<policy::AddressableByteLimit>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserOverrides {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dom_utf8_bytes: Option<policy::AddressableByteLimit>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ax_json_utf8_bytes: Option<policy::AddressableByteLimit>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_events: Option<policy::EventLimit>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_resources: Option<policy::ResourceLimit>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_accessibility_nodes: Option<policy::AccessibilityNodeLimit>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
#[allow(clippy::struct_field_names)] // These names mirror public document policy fields.
pub struct DocumentOverrides {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_input_bytes: Option<policy::AddressableByteLimit>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_nodes: Option<CountLimit>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_depth: Option<StepLimit>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
#[allow(clippy::struct_field_names)] // These names mirror public locator policy fields.
pub struct LocatorOverrides {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_selector_visits: Option<CountLimit>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_query_bytes: Option<policy::AddressableByteLimit>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_query_steps: Option<StepLimit>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_regions: Option<StepLimit>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_matches: Option<CountLimit>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_captures: Option<CountLimit>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_output_bytes: Option<policy::AddressableByteLimit>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
#[allow(clippy::struct_field_names)] // These names mirror public Search policy fields.
pub struct SearchOverrides {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub providers: Option<Vec<policy::search::ProviderSelection>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_in_flight: Option<NonZeroUsize>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_browser_in_flight: Option<NonZeroUsize>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_results_per_provider: Option<NonZeroU16>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_total_results: Option<NonZeroU32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_retained_content_bytes: Option<policy::AddressableByteLimit>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub maximum_elapsed: Option<policy::MaximumElapsed>,
}

impl PolicyOverrides {
    pub fn apply(&self, target: &mut Policy) {
        if let Some(page) = &self.page
            && let Some(acquisitions) = &page.acquisitions
        {
            target.page.acquisitions.clone_from(acquisitions);
        }
        if let Some(request) = &self.request {
            apply_request(request, target);
        }
        if let Some(documents) = &self.documents {
            apply_documents(documents, target);
        }
        if let Some(locators) = &self.locators {
            apply_locators(locators, target);
        }
        if let Some(value) = self.tuning {
            target.tuning = value;
        }
        if let Some(map) = &self.map {
            target.map.clone_from(map);
        }
        if let Some(search) = &self.search {
            apply_search(search, target);
        }
    }
}

const fn apply_request(overrides: &RequestOverrides, target: &mut Policy) {
    if let Some(value) = overrides.maximum_elapsed {
        target.request.maximum_elapsed = value;
    }
    if let Some(source) = &overrides.source {
        apply_source(source, target);
    }
    if let Some(browser) = &overrides.browser {
        apply_browser(browser, target);
    }
    if let Some(value) = overrides.direct_http_redirects {
        target.request.direct_http_redirects = value;
    }
}

const fn apply_source(overrides: &SourceOverrides, target: &mut Policy) {
    if let Some(value) = overrides.content_coded_bytes {
        target.request.source.content_coded_bytes = value;
    }
    if let Some(value) = overrides.representation_bytes {
        target.request.source.representation_bytes = value;
    }
    if let Some(value) = overrides.unicode_utf8_bytes {
        target.request.source.unicode_utf8_bytes = value;
    }
}

const fn apply_browser(overrides: &BrowserOverrides, target: &mut Policy) {
    if let Some(value) = overrides.dom_utf8_bytes {
        target.request.browser.dom_utf8_bytes = value;
    }
    if let Some(value) = overrides.ax_json_utf8_bytes {
        target.request.browser.ax_json_utf8_bytes = value;
    }
    if let Some(value) = overrides.max_events {
        target.request.browser.max_events = value;
    }
    if let Some(value) = overrides.max_resources {
        target.request.browser.max_resources = value;
    }
    if let Some(value) = overrides.max_accessibility_nodes {
        target.request.browser.max_accessibility_nodes = value;
    }
}

const fn apply_documents(overrides: &DocumentOverrides, target: &mut Policy) {
    if let Some(value) = overrides.max_input_bytes {
        target.documents.max_input_bytes = value;
    }
    if let Some(value) = overrides.max_nodes {
        target.documents.max_nodes = value;
    }
    if let Some(value) = overrides.max_depth {
        target.documents.max_depth = value;
    }
}

const fn apply_locators(overrides: &LocatorOverrides, target: &mut Policy) {
    if let Some(value) = overrides.max_selector_visits {
        target.locators.max_selector_visits = value;
    }
    if let Some(value) = overrides.max_query_bytes {
        target.locators.max_query_bytes = value;
    }
    if let Some(value) = overrides.max_query_steps {
        target.locators.max_query_steps = value;
    }
    if let Some(value) = overrides.max_regions {
        target.locators.max_regions = value;
    }
    if let Some(value) = overrides.max_matches {
        target.locators.max_matches = value;
    }
    if let Some(value) = overrides.max_captures {
        target.locators.max_captures = value;
    }
    if let Some(value) = overrides.max_output_bytes {
        target.locators.max_output_bytes = value;
    }
}

fn apply_search(overrides: &SearchOverrides, target: &mut Policy) {
    if let Some(value) = &overrides.providers {
        target.search.providers.clone_from(value);
    }
    if let Some(value) = overrides.max_in_flight {
        target.search.max_in_flight = value;
    }
    if let Some(value) = overrides.max_browser_in_flight {
        target.search.max_browser_in_flight = value;
    }
    if let Some(value) = overrides.max_results_per_provider {
        target.search.max_results_per_provider = value;
    }
    if let Some(value) = overrides.max_total_results {
        target.search.max_total_results = value;
    }
    if let Some(value) = overrides.max_retained_content_bytes {
        target.search.max_retained_content_bytes = value;
    }
    if let Some(value) = overrides.maximum_elapsed {
        target.search.maximum_elapsed = value;
    }
}
