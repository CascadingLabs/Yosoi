//! Static, provider-neutral accessibility-tree documents and exact locators.

mod evaluate;
mod parse;
mod types;

pub use types::{AccessibilityCompleteness, AccessibilityParseError, ParsedAccessibilityDocument};

pub fn parse_failure(error: &AccessibilityParseError) -> crate::LocateFailure {
    error.clone().into_failure()
}
