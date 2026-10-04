use serde::{Deserialize, Serialize};

use crate::PolicyError;

use super::{
    AccessibilityNodeLimit, AddressableByteLimit, DirectHttpRedirects, EventLimit, MaximumElapsed,
    ResourceLimit,
};

/// Positive limits for independent source-response byte domains.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SourceLimits {
    /// Maximum admitted content-coded response bytes.
    pub content_coded_bytes: AddressableByteLimit,
    /// Maximum retained decoded representation bytes.
    pub representation_bytes: AddressableByteLimit,
    /// Maximum derived Unicode view size, measured in UTF-8 bytes.
    pub unicode_utf8_bytes: AddressableByteLimit,
}

impl Default for SourceLimits {
    fn default() -> Self {
        Self {
            content_coded_bytes: AddressableByteLimit::default_content_coded(),
            representation_bytes: AddressableByteLimit::default_representation(),
            unicode_utf8_bytes: AddressableByteLimit::default_unicode_utf8(),
        }
    }
}

/// Positive limits for browser-produced byte, event, resource, and AX-node domains.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserLimits {
    /// Maximum retained rendered-DOM UTF-8 bytes.
    pub dom_utf8_bytes: AddressableByteLimit,
    /// Maximum retained accessibility-tree JSON UTF-8 bytes.
    pub ax_json_utf8_bytes: AddressableByteLimit,
    /// Maximum admitted browser observation events.
    pub max_events: EventLimit,
    /// Maximum browser resources admitted to one capture.
    pub max_resources: ResourceLimit,
    /// Maximum accessibility nodes admitted to one capture.
    pub max_accessibility_nodes: AccessibilityNodeLimit,
}

impl Default for BrowserLimits {
    fn default() -> Self {
        Self {
            dom_utf8_bytes: AddressableByteLimit::default_browser_bytes(),
            ax_json_utf8_bytes: AddressableByteLimit::default_browser_bytes(),
            max_events: EventLimit::default(),
            max_resources: ResourceLimit::default_resource_count(),
            max_accessibility_nodes: AccessibilityNodeLimit::default_accessibility_node_count(),
        }
    }
}

/// Shared attempt limits and Direct HTTP redirect behavior.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    /// Shared monotonic attempt deadline, in microseconds.
    pub maximum_elapsed: MaximumElapsed,
    /// Source-response byte-domain limits.
    pub source: SourceLimits,
    /// Browser byte and count limits.
    pub browser: BrowserLimits,
    /// Automatic native HTTP redirects; browser navigation owns its redirect semantics.
    pub direct_http_redirects: DirectHttpRedirects,
}

impl Request {
    /// Creates a complete request policy and verifies platform addressability.
    pub fn new(
        maximum_elapsed: MaximumElapsed,
        source: SourceLimits,
        browser: BrowserLimits,
        direct_http_redirects: DirectHttpRedirects,
    ) -> Result<Self, PolicyError> {
        let request = Self {
            maximum_elapsed,
            source,
            browser,
            direct_http_redirects,
        };
        request.validate()?;
        Ok(request)
    }

    pub(crate) fn validate(&self) -> Result<(), PolicyError> {
        self.maximum_elapsed
            .to_capture_deadline()
            .map_err(|_| PolicyError::ZeroMaximumElapsed)?;
        self.source.content_coded_bytes.as_usize()?;
        self.source.representation_bytes.as_usize()?;
        self.source.unicode_utf8_bytes.as_usize()?;
        self.browser.dom_utf8_bytes.as_usize()?;
        self.browser.ax_json_utf8_bytes.as_usize()?;
        self.browser.max_events.as_usize()?;
        self.browser.max_resources.to_nonzero()?;
        self.browser.max_accessibility_nodes.to_nonzero()?;
        if let DirectHttpRedirects::Follow { max_hops, .. } = self.direct_http_redirects {
            max_hops.nonzero()?;
        }
        Ok(())
    }
}
