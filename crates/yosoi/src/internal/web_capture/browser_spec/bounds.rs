use super::{BrowserBudgetScope, BrowserLimitEnforcement};
use std::{
    collections::HashSet,
    num::{NonZeroU32, NonZeroU64},
};
use thiserror::Error;
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum BrowserByteDomain {
    CdpDecodedBody,
    DecodedSourceUtf8,
    RenderedDomUtf8,
    AccessibilityJsonUtf8,
    RuntimeDiagnosticUtf8,
    ScreenshotPng,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BrowserByteBound {
    domain: BrowserByteDomain,
    limit: NonZeroU64,
    enforcement: BrowserLimitEnforcement,
    budget_scope: BrowserBudgetScope,
}
impl BrowserByteBound {
    pub const fn new(
        domain: BrowserByteDomain,
        limit: NonZeroU64,
        enforcement: BrowserLimitEnforcement,
        budget_scope: BrowserBudgetScope,
    ) -> Self {
        Self {
            domain,
            limit,
            enforcement,
            budget_scope,
        }
    }
    pub const fn domain(self) -> BrowserByteDomain {
        self.domain
    }
    pub const fn limit(self) -> NonZeroU64 {
        self.limit
    }
    pub const fn enforcement(self) -> BrowserLimitEnforcement {
        self.enforcement
    }
    pub const fn budget_scope(self) -> BrowserBudgetScope {
        self.budget_scope
    }
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserProviderBounds {
    byte_bounds: Vec<BrowserByteBound>,
    /// Shared provider/lifecycle cap, exposed as the resolved observation event limit.
    max_events: NonZeroU64,
    max_resources: NonZeroU32,
    max_accessibility_nodes: NonZeroU32,
}
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BrowserBoundsError {
    #[error("a browser byte domain is duplicated")]
    DuplicateByteDomain,
    #[error("provider bounds exceed addressable memory")]
    UnaddressableBound,
    #[error("certified byte collection uses post-materialization retention")]
    UnsupportedEnforcement,
}
impl BrowserProviderBounds {
    pub fn new(
        byte_bounds: Vec<BrowserByteBound>,
        max_events: NonZeroU64,
        max_resources: NonZeroU32,
        max_accessibility_nodes: NonZeroU32,
    ) -> Result<Self, BrowserBoundsError> {
        if usize::try_from(max_events.get()).is_err()
            || byte_bounds
                .iter()
                .any(|bound| usize::try_from(bound.limit().get()).is_err())
        {
            return Err(BrowserBoundsError::UnaddressableBound);
        }
        if byte_bounds.iter().any(|bound| {
            let expected = match bound.domain() {
                BrowserByteDomain::CdpDecodedBody
                | BrowserByteDomain::DecodedSourceUtf8
                | BrowserByteDomain::RenderedDomUtf8
                | BrowserByteDomain::AccessibilityJsonUtf8
                | BrowserByteDomain::RuntimeDiagnosticUtf8
                | BrowserByteDomain::ScreenshotPng => {
                    BrowserLimitEnforcement::RetentionAfterProviderMaterialization
                }
            };
            bound.enforcement() != expected
        }) {
            return Err(BrowserBoundsError::UnsupportedEnforcement);
        }
        let mut seen = HashSet::new();
        if byte_bounds.iter().any(|b| !seen.insert(b.domain)) {
            return Err(BrowserBoundsError::DuplicateByteDomain);
        }
        Ok(Self {
            byte_bounds,
            max_events,
            max_resources,
            max_accessibility_nodes,
        })
    }
    pub fn byte_bounds(&self) -> &[BrowserByteBound] {
        &self.byte_bounds
    }
    pub const fn max_events(&self) -> NonZeroU64 {
        self.max_events
    }
    pub const fn max_resources(&self) -> NonZeroU32 {
        self.max_resources
    }
    pub const fn max_accessibility_nodes(&self) -> NonZeroU32 {
        self.max_accessibility_nodes
    }
}
