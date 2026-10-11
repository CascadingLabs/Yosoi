//! Typed expectations for bounded eventual assertions.

use crate::{
    assertions::LocalAssertion,
    flow::{Condition, Continuation, Step},
    request::CancellationToken,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::time::Duration;

/// Maximum number of clauses in an [`Expectation::All`] group.
pub const MAX_EXPECTATIONS: usize = 128;
/// Maximum number of response JSON Pointer matches.
pub const MAX_RESPONSE_JSON_MATCHES: usize = 32;

/// One serializable condition that an eventual assertion can observe.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Expectation {
    /// A typed DOM condition, checked against the current document.
    Condition { condition: Condition },
    /// A local Rust Contract assertion; executable code is bound in memory only.
    Contract { assertion: LocalAssertion },
    /// An exact accessible name, optionally constrained to a role.
    Accessibility {
        name: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        role: Option<String>,
    },
    /// A response matching the full URL and any supplied response fields.
    Response {
        url: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        method: Option<String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        status: Option<u16>,
        #[serde(default, skip_serializing_if = "Vec::is_empty")]
        json: Vec<JsonMatch>,
    },
    /// Every clause must be confirmed in the same result cycle. Each source
    /// keeps its own evidence and timestamp; a response may be retained from
    /// earlier in the wait while DOM and accessibility evidence is fresh.
    All { expectations: Vec<Self> },
}

impl Expectation {
    /// Waits for this expectation without a separate trigger action.
    pub fn until(self) -> Step {
        Step::until_without_trigger(self)
    }
}

impl From<Condition> for Expectation {
    fn from(condition: Condition) -> Self {
        Self::Condition { condition }
    }
}

impl From<LocalAssertion> for Expectation {
    fn from(assertion: LocalAssertion) -> Self {
        Self::Contract { assertion }
    }
}

/// A JSON Pointer match against a response body parsed as JSON.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct JsonMatch {
    /// RFC 6901 JSON Pointer, such as `/cart/quantity`.
    pub pointer: String,
    /// Expected JSON value at `pointer`.
    pub value: Value,
}

/// Builder for a response expectation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResponseExpectation {
    pub(crate) url: String,
    pub(crate) method: Option<String>,
    pub(crate) status: Option<u16>,
    pub(crate) json: Vec<JsonMatch>,
}

impl ResponseExpectation {
    /// Requires this exact HTTP method, in addition to the full URL.
    pub fn method(mut self, method: impl Into<String>) -> Self {
        self.method = Some(method.into());
        self
    }

    /// Requires this status code, in addition to the full URL.
    pub const fn status(mut self, status: u16) -> Self {
        self.status = Some(status);
        self
    }

    /// Requires one JSON Pointer in the response body to equal `value`.
    pub fn json(mut self, pointer: impl Into<String>, value: impl Into<Value>) -> Self {
        if self.json.len() <= MAX_RESPONSE_JSON_MATCHES {
            self.json.push(JsonMatch {
                pointer: pointer.into(),
                value: value.into(),
            });
        }
        self
    }

    /// Waits for this response expectation without a trigger action.
    pub fn until(self) -> Step {
        Step::until_without_trigger(self)
    }
}

impl From<ResponseExpectation> for Expectation {
    fn from(response: ResponseExpectation) -> Self {
        Self::Response {
            url: response.url,
            method: response.method,
            status: response.status,
            json: response.json,
        }
    }
}

/// Builder for an exact accessible-name expectation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AccessibilityExpectation {
    pub(crate) name: String,
    pub(crate) role: Option<String>,
}

impl AccessibilityExpectation {
    /// Also requires the accessible node to have this role.
    pub fn role(mut self, role: impl Into<String>) -> Self {
        self.role = Some(role.into());
        self
    }

    /// Waits for this accessibility expectation without a trigger action.
    pub fn until(self) -> Step {
        Step::until_without_trigger(self)
    }
}

impl From<AccessibilityExpectation> for Expectation {
    fn from(accessibility: AccessibilityExpectation) -> Self {
        Self::Accessibility {
            name: accessibility.name,
            role: accessibility.role,
        }
    }
}

/// Builder for a conjunction of expectations.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AllExpectation {
    pub(crate) expectations: Vec<Expectation>,
}

impl AllExpectation {
    /// Waits for every clause without a trigger action.
    pub fn until(self) -> Step {
        Step::until_without_trigger(self)
    }
}

impl From<AllExpectation> for Expectation {
    fn from(all: AllExpectation) -> Self {
        Self::All {
            expectations: all.expectations,
        }
    }
}

/// A transient `Step::until` argument that carries existing Step modifiers.
///
/// Modifiers are lowered onto the compound Until step. They are intentionally
/// omitted from the serialized expectation model.
#[derive(Clone, Debug)]
pub struct UntilExpectation {
    pub(crate) expectation: Expectation,
    pub(crate) timeout: Option<Duration>,
    pub(crate) on_failure: Option<Continuation>,
    pub(crate) on_cancellation: Option<Continuation>,
    pub(crate) cancellation: Option<CancellationToken>,
}

impl UntilExpectation {
    pub(crate) const fn new(expectation: Expectation) -> Self {
        Self {
            expectation,
            timeout: None,
            on_failure: None,
            on_cancellation: None,
            cancellation: None,
        }
    }
}

impl From<Expectation> for UntilExpectation {
    fn from(expectation: Expectation) -> Self {
        Self::new(expectation)
    }
}

impl From<Condition> for UntilExpectation {
    fn from(condition: Condition) -> Self {
        Self::new(condition.into())
    }
}

impl From<LocalAssertion> for UntilExpectation {
    fn from(assertion: LocalAssertion) -> Self {
        Self::new(assertion.into())
    }
}

impl From<ResponseExpectation> for UntilExpectation {
    fn from(response: ResponseExpectation) -> Self {
        Self::new(response.into())
    }
}

impl From<AccessibilityExpectation> for UntilExpectation {
    fn from(accessibility: AccessibilityExpectation) -> Self {
        Self::new(accessibility.into())
    }
}

impl From<AllExpectation> for UntilExpectation {
    fn from(all: AllExpectation) -> Self {
        Self::new(all.into())
    }
}

/// Constructs a typed DOM condition that matches at least one element.
pub fn exists(selector: impl Into<String>) -> Expectation {
    Condition::Exists {
        selector: selector.into(),
    }
    .into()
}

/// Constructs a typed DOM condition that matches at least one visible element.
pub fn visible(selector: impl Into<String>) -> Expectation {
    Condition::Visible {
        selector: selector.into(),
    }
    .into()
}

/// Constructs a typed DOM condition with a minimum matching element count.
pub fn count_at_least(selector: impl Into<String>, count: u64) -> Expectation {
    Condition::CountAtLeast {
        selector: selector.into(),
        count,
    }
    .into()
}

/// Constructs an exact full-URL response expectation.
pub fn response(url: impl Into<String>) -> ResponseExpectation {
    ResponseExpectation {
        url: url.into(),
        method: None,
        status: None,
        json: Vec::new(),
    }
}

/// Constructs an exact accessible-name expectation.
pub fn ax(name: impl Into<String>) -> AccessibilityExpectation {
    AccessibilityExpectation {
        name: name.into(),
        role: None,
    }
}

/// Requires each supplied expectation to be confirmed in one result cycle.
pub fn all(expectations: impl IntoIterator<Item = Expectation>) -> AllExpectation {
    AllExpectation {
        expectations: expectations
            .into_iter()
            .take(MAX_EXPECTATIONS + 1)
            .collect(),
    }
}
