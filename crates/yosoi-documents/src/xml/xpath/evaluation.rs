use std::mem::swap;

use roxmltree::Node;

use super::super::{QueryWorkBudget, XmlError, enforce_match_limit};
use super::{Axis, NodeTest, Predicate, Step, XPath};

impl XPath {
    pub(in crate::xml) fn evaluate<'tree, 'input>(
        &self,
        tree: &'tree roxmltree::Document<'input>,
        context: Node<'tree, 'input>,
        maximum: u64,
        work_budget: &mut QueryWorkBudget,
    ) -> Result<Vec<Node<'tree, 'input>>, XmlError> {
        let mut contexts = vec![if self.absolute { tree.root() } else { context }];
        let mut selected = Vec::new();
        let mut group = Vec::new();
        let mut filtered = Vec::new();
        for step in &self.steps {
            selected.clear();
            for parent in &contexts {
                match step.axis {
                    Axis::Child => {
                        select_axis_group(*parent, step, work_budget, &mut group, &mut filtered)?;
                        selected.append(&mut group);
                    }
                    Axis::Descendant => {
                        for descendant_or_self in parent.descendants() {
                            work_budget.visit()?;
                            select_axis_group(
                                descendant_or_self,
                                step,
                                work_budget,
                                &mut group,
                                &mut filtered,
                            )?;
                            selected.append(&mut group);
                            enforce_match_limit(selected.len(), maximum)?;
                        }
                    }
                    Axis::SelfNode => {
                        work_budget.visit()?;
                        if step.test.matches(*parent) {
                            group.clear();
                            group.push(*parent);
                            apply_predicates(
                                &mut group,
                                &step.predicates,
                                work_budget,
                                &mut filtered,
                            )?;
                            selected.append(&mut group);
                        }
                    }
                }
                enforce_match_limit(selected.len(), maximum)?;
            }
            match step.axis {
                Axis::Child if contexts.len() > 1 => selected.sort(),
                Axis::Descendant => {
                    selected.sort();
                    selected.dedup_by_key(|node| node.id());
                }
                Axis::Child | Axis::SelfNode => {}
            }
            swap(&mut contexts, &mut selected);
            enforce_match_limit(contexts.len(), maximum)?;
        }
        Ok(contexts)
    }
}

impl NodeTest {
    fn matches(&self, node: Node<'_, '_>) -> bool {
        if !node.is_element() {
            return false;
        }
        match self {
            Self::AnyElement => true,
            Self::ExpandedName { namespace, local } => {
                let name = node.tag_name();
                name.namespace() == namespace.as_deref() && name.name() == local
            }
        }
    }
}

impl Predicate {
    fn matches_node(
        &self,
        node: Node<'_, '_>,
        work_budget: &mut QueryWorkBudget,
    ) -> Result<bool, XmlError> {
        match self {
            Self::AttributeExists { namespace, local } => {
                for attribute in node.attributes() {
                    work_budget.visit()?;
                    if attribute.name() == local && attribute.namespace() == namespace.as_deref() {
                        return Ok(true);
                    }
                }
                Ok(false)
            }
            Self::AttributeEquals {
                namespace,
                local,
                value,
            } => {
                for attribute in node.attributes() {
                    work_budget.visit()?;
                    if attribute.name() == local
                        && attribute.namespace() == namespace.as_deref()
                        && attribute.value() == value
                    {
                        return Ok(true);
                    }
                }
                Ok(false)
            }
            Self::LocalNameEquals(wanted) => Ok(node.tag_name().name() == wanted),
            Self::Position(_) => Ok(true),
        }
    }
}

fn select_axis_group<'tree, 'input>(
    context: Node<'tree, 'input>,
    step: &Step,
    work_budget: &mut QueryWorkBudget,
    candidates: &mut Vec<Node<'tree, 'input>>,
    filtered: &mut Vec<Node<'tree, 'input>>,
) -> Result<(), XmlError> {
    candidates.clear();
    for node in context.children().filter(Node::is_element) {
        work_budget.visit()?;
        if step.test.matches(node) {
            candidates.push(node);
        }
    }
    apply_predicates(candidates, &step.predicates, work_budget, filtered)
}

fn apply_predicates<'tree, 'input>(
    nodes: &mut Vec<Node<'tree, 'input>>,
    predicates: &[Predicate],
    work_budget: &mut QueryWorkBudget,
    filtered: &mut Vec<Node<'tree, 'input>>,
) -> Result<(), XmlError> {
    for predicate in predicates {
        if let Predicate::Position(position) = predicate {
            let selected = position
                .checked_sub(1)
                .and_then(|index| nodes.get(index))
                .copied();
            nodes.clear();
            nodes.extend(selected);
            continue;
        }

        filtered.clear();
        for node in nodes.drain(..) {
            work_budget.visit()?;
            if predicate.matches_node(node, work_budget)? {
                filtered.push(node);
            }
        }
        swap(nodes, filtered);
    }
    Ok(())
}
