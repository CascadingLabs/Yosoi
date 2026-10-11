use crate::internal::documents::LocateFailure;

use super::{HTML_NAMESPACE, SelectorVisitBudget};

/// Shared element-name and attribute access for CSS and XPath evaluation.
pub trait SelectorElement {
    fn local_name(&self) -> Option<&str>;
    fn namespace_uri(&self) -> Option<&str>;
    fn attribute_value(
        &self,
        requested_name: &str,
        budget: &mut SelectorVisitBudget,
    ) -> Result<Option<String>, LocateFailure>;
}

pub fn element_name_matches<E: SelectorElement>(element: &E, expected: &str) -> bool {
    let Some(local_name) = element.local_name() else {
        return false;
    };
    if element.namespace_uri() == Some(HTML_NAMESPACE) {
        local_name.eq_ignore_ascii_case(expected)
    } else {
        local_name == expected
    }
}

pub fn element_attribute<E: SelectorElement>(
    element: &E,
    requested_name: &str,
    budget: &mut SelectorVisitBudget,
) -> Result<Option<String>, LocateFailure> {
    element.attribute_value(requested_name, budget)
}

pub fn canonical_attribute_name<E: SelectorElement>(element: &E, requested_name: &str) -> String {
    if element.namespace_uri() == Some(HTML_NAMESPACE) {
        requested_name.to_ascii_lowercase()
    } else {
        requested_name.to_owned()
    }
}
