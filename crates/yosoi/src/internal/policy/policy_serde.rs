use super::policy::Network;
use crate::browser as browser_config;
use serde::{
    Deserialize, Deserializer, Serialize, Serializer, de::Error as _, ser::Error as SerError,
};

use crate::internal::policy::{
    policy::{Documents, FlowPolicy, Locators, Map, Page, Request, Search, Tuning},
    policy_value::Policy,
};

impl Serialize for Policy {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        self.validate().map_err(SerError::custom)?;
        PolicyRef {
            network: &self.network,
            browser: &self.browser,
            default_action_timeout_ms: self.default_action_timeout_ms,
            flow: self.flow,
            page: &self.page,
            request: &self.request,
            documents: &self.documents,
            locators: &self.locators,
            tuning: self.tuning,
            map: &self.map,
            search: &self.search,
        }
        .serialize(serializer)
    }
}

impl<'de> Deserialize<'de> for Policy {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let values = PolicyValues::deserialize(deserializer)?;
        let policy = Self {
            network: values.network,
            browser: values.browser,
            default_action_timeout_ms: values.default_action_timeout_ms,
            page: values.page,
            request: values.request,
            documents: values.documents,
            locators: values.locators,
            tuning: values.tuning,
            map: values.map,
            search: values.search,
            flow: values.flow,
        };
        policy.validate().map_err(D::Error::custom)?;
        Ok(policy)
    }
}

#[derive(Serialize)]
struct PolicyRef<'a> {
    #[serde(skip_serializing_if = "Network::is_default")]
    network: &'a Network,
    #[serde(skip_serializing_if = "browser_config::BrowserConfig::is_default")]
    browser: &'a browser_config::BrowserConfig,
    default_action_timeout_ms: u64,
    flow: FlowPolicy,
    page: &'a Page,
    request: &'a Request,
    documents: &'a Documents,
    locators: &'a Locators,
    #[serde(skip_serializing_if = "Tuning::is_default")]
    tuning: Tuning,
    map: &'a Map,
    search: &'a Search,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PolicyValues {
    #[serde(default)]
    network: Network,
    #[serde(default)]
    browser: browser_config::BrowserConfig,
    #[serde(default = "default_action_timeout_ms")]
    default_action_timeout_ms: u64,
    page: Page,
    request: Request,
    documents: Documents,
    locators: Locators,
    #[serde(default)]
    tuning: Tuning,
    #[serde(default)]
    map: Map,
    #[serde(default = "Search::disabled")]
    search: Search,
    #[serde(default)]
    flow: FlowPolicy,
}

const fn default_action_timeout_ms() -> u64 {
    10_000
}
