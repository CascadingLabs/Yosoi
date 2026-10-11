use thiserror::Error;

use crate::internal::documents::accessibility::{
    self, AccessibilityParseError, ParsedAccessibilityDocument,
};
use crate::internal::documents::decoded_text::{self, DecodedTextDocument, DecodedTextParseError};
use crate::internal::documents::html::{self, HtmlParseError, ParsedHtmlDocument};
use crate::internal::documents::json::{
    self, JsonParseError, ParsedJsonDocument, parse_json_document,
};
use crate::internal::documents::rendered_dom::{self, RenderedDomDocument, RenderedDomParseError};
use crate::internal::documents::xml::{self, XmlDocument, XmlError};
use crate::internal::documents::{
    Document, DocumentClass, LocateFailure, LocateOutcome, Plan, ResourceBudget,
};

/// Domain-owned execution tuning resolved from an SDK operation.
///
/// Additional modes belong here only when a measured document strategy needs
/// one. Resource budgets remain independent correctness and safety limits.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum DocumentExecutionTuning {
    /// Preserve the current parser and locator strategy.
    #[default]
    Default,
}

/// A representation-specific parse failure behind the common document API.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum DocumentParseError {
    #[error(transparent)]
    Html(#[from] HtmlParseError),
    #[error(transparent)]
    Xml(#[from] XmlError),
    #[error(transparent)]
    Json(#[from] JsonParseError),
    #[error(transparent)]
    Text(#[from] DecodedTextParseError),
    #[error(transparent)]
    RenderedDom(#[from] RenderedDomParseError),
    #[error(transparent)]
    Accessibility(#[from] AccessibilityParseError),
}

impl DocumentParseError {
    fn locate_failure(&self) -> LocateFailure {
        match self {
            Self::Html(error) => html::parse_failure(error),
            Self::Xml(error) => xml::parse_failure(error),
            Self::Json(error) => json::parse_failure(error),
            Self::Text(error) => decoded_text::parse_failure(error),
            Self::RenderedDom(error) => rendered_dom::parse_failure(error),
            Self::Accessibility(error) => accessibility::parse_failure(error),
        }
    }
}

/// One parsed immutable document that retains its parse-time resource budget.
#[derive(Debug)]
pub struct ParsedDocument<'document> {
    inner: ParsedDocumentKind<'document>,
    budget: ResourceBudget,
    tuning: DocumentExecutionTuning,
}

#[derive(Debug)]
enum ParsedDocumentKind<'document> {
    Html(ParsedHtmlDocument),
    Xml(XmlDocument<'document>),
    Json(ParsedJsonDocument),
    Text(DecodedTextDocument<'document>),
    RenderedDom(RenderedDomDocument),
    Accessibility(ParsedAccessibilityDocument),
}

impl Document {
    /// Parses this document once using the default resource budget.
    pub fn parse(&self) -> Result<ParsedDocument<'_>, DocumentParseError> {
        self.parse_with_budget(ResourceBudget::default())
    }

    /// Parses this document once using an explicitly derived operation budget.
    pub fn parse_with_budget(
        &self,
        budget: ResourceBudget,
    ) -> Result<ParsedDocument<'_>, DocumentParseError> {
        self.parse_with_tuning(budget, DocumentExecutionTuning::Default)
    }

    /// Parses once with operation-owned tuning and independent resource limits.
    pub fn parse_with_tuning(
        &self,
        budget: ResourceBudget,
        tuning: DocumentExecutionTuning,
    ) -> Result<ParsedDocument<'_>, DocumentParseError> {
        let inner = match self.class() {
            DocumentClass::SourceHtml => {
                ParsedDocumentKind::Html(ParsedHtmlDocument::parse(self, budget)?)
            }
            DocumentClass::SourceXml => ParsedDocumentKind::Xml(XmlDocument::parse(self, budget)?),
            DocumentClass::SourceJson => {
                ParsedDocumentKind::Json(parse_json_document(self, budget)?)
            }
            DocumentClass::SourceText => {
                ParsedDocumentKind::Text(DecodedTextDocument::parse(self, budget)?)
            }
            DocumentClass::RenderedDom => {
                ParsedDocumentKind::RenderedDom(RenderedDomDocument::parse(self, budget)?)
            }
            DocumentClass::AccessibilityTree => {
                ParsedDocumentKind::Accessibility(ParsedAccessibilityDocument::parse(self, budget)?)
            }
        };
        Ok(ParsedDocument {
            inner,
            budget,
            tuning,
        })
    }

    /// Parses and locates this document using the default resource budget.
    pub fn locate(&self, plan: &Plan) -> LocateOutcome {
        self.locate_with_budget(plan, ResourceBudget::default())
    }

    /// Parses and locates this document using an explicitly derived operation budget.
    pub fn locate_with_budget(&self, plan: &Plan, budget: ResourceBudget) -> LocateOutcome {
        self.locate_with_tuning(plan, budget, DocumentExecutionTuning::Default)
    }

    /// Locates using one operation's tuning and independent resource limits.
    pub fn locate_with_tuning(
        &self,
        plan: &Plan,
        budget: ResourceBudget,
        tuning: DocumentExecutionTuning,
    ) -> LocateOutcome {
        match tuning {
            DocumentExecutionTuning::Default => self.locate_default(plan, budget),
        }
    }

    fn locate_default(&self, plan: &Plan, budget: ResourceBudget) -> LocateOutcome {
        if let Err(failure) = self.validate_plan(plan, budget) {
            return LocateOutcome::Failed { failure };
        }
        if self.class() == DocumentClass::SourceHtml {
            let dispatch = html::try_locate_streaming(self, plan, budget);
            #[cfg(debug_assertions)]
            dispatch.trace_if_requested();
            match dispatch {
                html::HtmlLocateDispatch::Completed { outcome, .. }
                | html::HtmlLocateDispatch::Terminal { outcome } => return outcome,
                html::HtmlLocateDispatch::RetainedTree { .. } => {
                    // The candidate used only resident immutable bytes. A rejected
                    // attempt publishes no findings; HTML5 reparses those bytes.
                }
            }
        }
        match self.parse_with_tuning(budget, DocumentExecutionTuning::Default) {
            Ok(parsed) => parsed.locate(plan),
            Err(error) => LocateOutcome::Failed {
                failure: error.locate_failure(),
            },
        }
    }
}

impl ParsedDocument<'_> {
    /// Returns the domain-owned tuning selected for later locations.
    pub const fn selected_tuning(&self) -> DocumentExecutionTuning {
        self.tuning
    }

    /// Locates against the parsed representation using its parse-time budget.
    pub fn locate(&self, plan: &Plan) -> LocateOutcome {
        self.locate_with_tuning(plan, self.tuning)
    }

    /// Locates against the parsed representation with operation-owned tuning.
    pub fn locate_with_tuning(
        &self,
        plan: &Plan,
        tuning: DocumentExecutionTuning,
    ) -> LocateOutcome {
        match tuning {
            DocumentExecutionTuning::Default => self.locate_default(plan),
        }
    }

    fn locate_default(&self, plan: &Plan) -> LocateOutcome {
        if let Err(failure) = plan.validate_budget(self.budget) {
            return LocateOutcome::Failed { failure };
        }
        match &self.inner {
            ParsedDocumentKind::Html(document) => document.locate_with_budget(plan, self.budget),
            ParsedDocumentKind::Xml(document) => document.locate_with_budget(plan, self.budget),
            ParsedDocumentKind::Json(document) => document.locate_with_budget(plan, self.budget),
            ParsedDocumentKind::Text(document) => {
                match document.locate_with_budget(plan, self.budget) {
                    Ok(located) => located.materialize(),
                    Err(failure) => LocateOutcome::Failed { failure },
                }
            }
            ParsedDocumentKind::RenderedDom(document) => {
                document.locate_with_budget(plan, self.budget)
            }
            ParsedDocumentKind::Accessibility(document) => {
                document.locate_with_budget(plan, self.budget)
            }
        }
    }
}
