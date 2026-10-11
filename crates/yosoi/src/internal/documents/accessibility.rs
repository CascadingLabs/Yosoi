//! Static, provider-neutral accessibility-tree documents and exact locators.

use crate::internal::documents as yosoi_documents;

mod evaluate;
mod parse;
mod types;

pub use types::{AccessibilityCompleteness, AccessibilityParseError, ParsedAccessibilityDocument};

pub fn parse_failure(error: &AccessibilityParseError) -> yosoi_documents::LocateFailure {
    error.clone().into_failure()
}
