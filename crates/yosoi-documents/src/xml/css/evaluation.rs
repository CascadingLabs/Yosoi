use roxmltree::Node;

use super::super::{QueryWorkBudget, XmlError, enforce_match_limit};
use super::{
    AttributeTest, Combinator, CompoundSelector, NameTest, NamespaceTest, Selector, SelectorList,
    SimpleCondition,
};

impl SelectorList {
    pub(in crate::xml) fn evaluate<'tree, 'input>(
        &self,
        context: Node<'tree, 'input>,
        maximum: u64,
        work_budget: &mut QueryWorkBudget,
    ) -> Result<Vec<Node<'tree, 'input>>, XmlError> {
        let mut matches = Vec::new();
        for node in context.descendants().filter(Node::is_element) {
            work_budget.visit()?;
            if node == context {
                continue;
            }
            let mut selected = false;
            for selector in &self.selectors {
                if selector.matches(node, work_budget)? {
                    selected = true;
                    break;
                }
            }
            if selected {
                matches.push(node);
                enforce_match_limit(matches.len(), maximum)?;
            }
        }
        Ok(matches)
    }
}

impl Selector {
    fn matches(
        &self,
        candidate: Node<'_, '_>,
        work_budget: &mut QueryWorkBudget,
    ) -> Result<bool, XmlError> {
        let Some(mut index) = self.compounds.len().checked_sub(1) else {
            return Ok(false);
        };
        let Some(compound) = self.compounds.get(index) else {
            return Ok(false);
        };
        if !compound.matches(candidate, work_budget)? {
            return Ok(false);
        }
        let mut current = candidate;
        while index > 0 {
            let Some(combinator_index) = index.checked_sub(1) else {
                return Ok(false);
            };
            let Some(combinator) = self.combinators.get(combinator_index) else {
                return Ok(false);
            };
            index = combinator_index;
            let Some(wanted) = self.compounds.get(index) else {
                return Ok(false);
            };
            match combinator {
                Combinator::Child => {
                    let Some(parent) = current.parent_element() else {
                        return Ok(false);
                    };
                    if !wanted.matches(parent, work_budget)? {
                        return Ok(false);
                    }
                    current = parent;
                }
                Combinator::Descendant => {
                    let mut ancestor = current.parent_element();
                    let mut found = None;
                    while let Some(node) = ancestor {
                        if wanted.matches(node, work_budget)? {
                            found = Some(node);
                            break;
                        }
                        ancestor = node.parent_element();
                    }
                    let Some(node) = found else {
                        return Ok(false);
                    };
                    current = node;
                }
            }
        }
        Ok(true)
    }
}

impl CompoundSelector {
    fn matches(
        &self,
        node: Node<'_, '_>,
        work_budget: &mut QueryWorkBudget,
    ) -> Result<bool, XmlError> {
        work_budget.visit()?;
        if let Some(name) = &self.name
            && !name.matches_element(node)
        {
            return Ok(false);
        }
        for condition in &self.conditions {
            let matches = match condition {
                SimpleCondition::Id(wanted) => unnamespaced_attribute(node, "id", work_budget)?
                    .is_some_and(|value| value == wanted),
                SimpleCondition::Class(wanted) => {
                    unnamespaced_attribute(node, "class", work_budget)?.is_some_and(|value| {
                        value.split_ascii_whitespace().any(|item| item == wanted)
                    })
                }
                SimpleCondition::Attribute(test) => test.matches(node, work_budget)?,
                SimpleCondition::FirstChild => is_first_element_child(node, work_budget)?,
            };
            if !matches {
                return Ok(false);
            }
        }
        Ok(true)
    }
}

impl NameTest {
    fn matches_element(&self, node: Node<'_, '_>) -> bool {
        if !node.is_element() {
            return false;
        }
        let name = node.tag_name();
        let namespace_matches = match &self.namespace {
            NamespaceTest::Any => true,
            NamespaceTest::None => name.namespace().is_none(),
            NamespaceTest::Uri(uri) => name.namespace() == Some(uri.as_str()),
        };
        namespace_matches
            && self
                .local_name
                .as_deref()
                .is_none_or(|local_name| name.name() == local_name)
    }

    fn matches_attribute(&self, attribute: &roxmltree::Attribute<'_, '_>) -> bool {
        let namespace_matches = match &self.namespace {
            NamespaceTest::Any => true,
            NamespaceTest::None => attribute.namespace().is_none(),
            NamespaceTest::Uri(uri) => attribute.namespace() == Some(uri.as_str()),
        };
        namespace_matches
            && self
                .local_name
                .as_deref()
                .is_none_or(|local_name| attribute.name() == local_name)
    }
}

impl AttributeTest {
    fn matches(
        &self,
        node: Node<'_, '_>,
        work_budget: &mut QueryWorkBudget,
    ) -> Result<bool, XmlError> {
        for attribute in node.attributes() {
            work_budget.visit()?;
            if self.name.matches_attribute(&attribute)
                && self
                    .value
                    .as_deref()
                    .is_none_or(|value| attribute.value() == value)
            {
                return Ok(true);
            }
        }
        Ok(false)
    }
}

fn unnamespaced_attribute<'tree>(
    node: Node<'tree, '_>,
    name: &str,
    work_budget: &mut QueryWorkBudget,
) -> Result<Option<&'tree str>, XmlError> {
    for attribute in node.attributes() {
        work_budget.visit()?;
        if attribute.name() == name && attribute.namespace().is_none() {
            return Ok(Some(attribute.value()));
        }
    }
    Ok(None)
}

fn is_first_element_child(
    node: Node<'_, '_>,
    work_budget: &mut QueryWorkBudget,
) -> Result<bool, XmlError> {
    let Some(parent) = node.parent() else {
        return Ok(false);
    };
    for sibling in parent.children() {
        work_budget.visit()?;
        if sibling.is_element() {
            return Ok(sibling.id() == node.id());
        }
    }
    Ok(false)
}
