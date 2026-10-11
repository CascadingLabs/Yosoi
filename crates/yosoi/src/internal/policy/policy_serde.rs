use serde::{
    Deserialize, Deserializer, Serialize, Serializer, de::Error as _, ser::Error as SerError,
};

use crate::internal::policy::{
    policy::{Documents, Locators, Map, Page, Request, Search, Tuning},
    policy_value::Policy,
};

impl Serialize for Policy {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        self.validate().map_err(SerError::custom)?;
        PolicyRef {
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
            page: values.page,
            request: values.request,
            documents: values.documents,
            locators: values.locators,
            tuning: values.tuning,
            map: values.map,
            search: values.search,
        };
        policy.validate().map_err(D::Error::custom)?;
        Ok(policy)
    }
}

#[derive(Serialize)]
struct PolicyRef<'a> {
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
}
