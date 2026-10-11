use crate::internal::documents::{LocateFailure, ResourceLimit};

use super::{
    Combinator, CssComplexSelector, ElementTree, ParsedHtmlDocument, TextSegment, TreeQuery,
    XPathAxis, XPathPath, compound_matches, limit_failure, parse_failure, select_tree_text,
    xpath_step_matches,
};

pub struct SelectorVisitBudget {
    maximum: u64,
    visited: u64,
}

#[derive(Clone, Copy, Default)]
struct VisitedSelectorStates {
    epoch: u32,
    steps: u64,
}

struct SelectorScratch {
    pending: Vec<(usize, usize)>,
    visited: Vec<VisitedSelectorStates>,
    epoch: u32,
}

impl SelectorScratch {
    fn new(element_count: usize) -> Self {
        Self {
            pending: Vec::new(),
            visited: vec![VisitedSelectorStates::default(); element_count],
            epoch: 0,
        }
    }

    fn begin(&mut self, candidate: usize, last_step: usize) {
        self.pending.clear();
        if let Some(epoch) = self.epoch.checked_add(1) {
            self.epoch = epoch;
        } else {
            self.visited.fill(VisitedSelectorStates::default());
            self.epoch = 1;
        }
        self.pending.push((candidate, last_step));
    }

    fn push(&mut self, state: (usize, usize)) {
        self.pending.push(state);
    }

    fn pop(&mut self) -> Option<(usize, usize)> {
        self.pending.pop()
    }

    fn mark_visited(&mut self, node_index: usize, step_index: usize) -> bool {
        let Ok(shift) = u32::try_from(step_index) else {
            return true;
        };
        let Some(bit) = 1_u64.checked_shl(shift) else {
            return true;
        };
        let Some(states) = self.visited.get_mut(node_index) else {
            return true;
        };
        if states.epoch != self.epoch {
            states.epoch = self.epoch;
            states.steps = 0;
        }
        if states.steps & bit != 0 {
            true
        } else {
            states.steps |= bit;
            false
        }
    }
}

impl SelectorVisitBudget {
    pub(in crate::internal::documents) const fn new(maximum: u64) -> Self {
        Self {
            maximum,
            visited: 0,
        }
    }

    pub(in crate::internal::documents) const fn charge(&mut self) -> Result<(), LocateFailure> {
        let Some(observed) = self.visited.checked_add(1) else {
            return Err(limit_failure(
                ResourceLimit::SelectorVisits,
                self.maximum,
                u64::MAX,
            ));
        };
        if observed > self.maximum {
            return Err(limit_failure(
                ResourceLimit::SelectorVisits,
                self.maximum,
                observed,
            ));
        }
        self.visited = observed;
        Ok(())
    }
}

impl ParsedHtmlDocument {
    pub(in crate::internal::documents) fn select(
        &self,
        query: &TreeQuery,
        scope: Option<usize>,
        maximum: u64,
        budget: &mut SelectorVisitBudget,
    ) -> Result<Vec<usize>, LocateFailure> {
        match query {
            TreeQuery::TreeTextContains(_) => {
                let text_index = self.text_index().map_err(|error| parse_failure(&error))?;
                select_tree(
                    &self.tree,
                    text_index.normalized(),
                    text_index.segments(),
                    query,
                    scope,
                    maximum,
                    budget,
                )
            }
            TreeQuery::Css(_) | TreeQuery::XPath(_) => {
                select_tree(&self.tree, "", &[], query, scope, maximum, budget)
            }
        }
    }
}

pub fn select_tree<T: ElementTree + ?Sized>(
    tree: &T,
    normalized_text: &str,
    text_segments: &[TextSegment],
    query: &TreeQuery,
    scope: Option<usize>,
    maximum: u64,
    budget: &mut SelectorVisitBudget,
) -> Result<Vec<usize>, LocateFailure> {
    match query {
        TreeQuery::Css(selector) => {
            let mut matches = Vec::new();
            let mut scratch = selector
                .groups
                .iter()
                .any(|group| group.steps.len() > 1)
                .then(|| SelectorScratch::new(tree.element_count()));
            for index in 0..tree.element_count() {
                budget.charge()?;
                if let Some(scope_index) = scope
                    && !tree.is_descendant(index, scope_index, budget)?
                {
                    continue;
                }
                let mut selected = false;
                for group in &selector.groups {
                    if css_matches(tree, index, group, scope, scratch.as_mut(), budget)? {
                        selected = true;
                        break;
                    }
                }
                if selected {
                    push_limited_match(&mut matches, index, maximum)?;
                }
            }
            Ok(matches)
        }
        TreeQuery::XPath(path) => {
            let mut matches = Vec::new();
            let mut scratch =
                (path.steps.len() > 1).then(|| SelectorScratch::new(tree.element_count()));
            for index in 0..tree.element_count() {
                budget.charge()?;
                if let Some(scope_index) = scope
                    && !tree.is_descendant(index, scope_index, budget)?
                {
                    continue;
                }
                if xpath_matches(tree, index, path, scope, scratch.as_mut(), budget)? {
                    push_limited_match(&mut matches, index, maximum)?;
                }
            }
            Ok(matches)
        }
        TreeQuery::TreeTextContains(expression) => select_tree_text(
            tree,
            normalized_text,
            text_segments,
            expression,
            scope,
            maximum,
            budget,
        ),
    }
}

fn css_matches<T: ElementTree + ?Sized>(
    tree: &T,
    candidate: usize,
    selector: &CssComplexSelector,
    scope: Option<usize>,
    scratch: Option<&mut SelectorScratch>,
    budget: &mut SelectorVisitBudget,
) -> Result<bool, LocateFailure> {
    let Some(last_step) = selector.steps.len().checked_sub(1) else {
        return Ok(false);
    };
    if last_step == 0 {
        budget.charge()?;
        let Some(step) = selector.steps.first() else {
            return Ok(false);
        };
        let Some(element) = tree.element(candidate) else {
            return Ok(false);
        };
        return compound_matches(element, &step.compound, budget);
    }
    let Some(scratch) = scratch else {
        return Ok(false);
    };
    scratch.begin(candidate, last_step);
    while let Some((node_index, step_index)) = scratch.pop() {
        budget.charge()?;
        if scratch.mark_visited(node_index, step_index) {
            continue;
        }
        let Some(step) = selector.steps.get(step_index) else {
            continue;
        };
        let Some(element) = tree.element(node_index) else {
            continue;
        };
        if !compound_matches(element, &step.compound, budget)? {
            continue;
        }
        if step_index == 0 {
            return Ok(true);
        }
        let Some(previous_index) = step_index.checked_sub(1) else {
            continue;
        };
        match step.relation {
            Some(Combinator::Child) => {
                if let Some(parent) = tree.parent(node_index)
                    && ancestor_is_in_scope(tree, parent, scope, budget)?
                {
                    scratch.push((parent, previous_index));
                }
            }
            Some(Combinator::Descendant) => {
                let mut ancestor = tree.parent(node_index);
                while let Some(parent) = ancestor {
                    budget.charge()?;
                    if ancestor_is_in_scope(tree, parent, scope, budget)? {
                        scratch.push((parent, previous_index));
                    } else {
                        break;
                    }
                    if Some(parent) == scope {
                        break;
                    }
                    ancestor = tree.parent(parent);
                }
            }
            None => {}
        }
    }
    Ok(false)
}

fn xpath_matches<T: ElementTree + ?Sized>(
    tree: &T,
    candidate: usize,
    path: &XPathPath,
    scope: Option<usize>,
    scratch: Option<&mut SelectorScratch>,
    budget: &mut SelectorVisitBudget,
) -> Result<bool, LocateFailure> {
    let Some(last_step) = path.steps.len().checked_sub(1) else {
        return Ok(false);
    };
    if last_step == 0 {
        budget.charge()?;
        let Some(step) = path.steps.first() else {
            return Ok(false);
        };
        let Some(element) = tree.element(candidate) else {
            return Ok(false);
        };
        if !xpath_step_matches(element, step, budget)? {
            return Ok(false);
        }
        return xpath_leading_axis_matches(tree, candidate, path, scope, budget);
    }
    let Some(scratch) = scratch else {
        return Ok(false);
    };
    scratch.begin(candidate, last_step);
    while let Some((node_index, step_index)) = scratch.pop() {
        budget.charge()?;
        if scratch.mark_visited(node_index, step_index) {
            continue;
        }
        let Some(step) = path.steps.get(step_index) else {
            continue;
        };
        let Some(element) = tree.element(node_index) else {
            continue;
        };
        if !xpath_step_matches(element, step, budget)? {
            continue;
        }
        if step_index == 0 {
            if xpath_leading_axis_matches(tree, node_index, path, scope, budget)? {
                return Ok(true);
            }
            continue;
        }
        let Some(previous_index) = step_index.checked_sub(1) else {
            continue;
        };
        match step.axis {
            XPathAxis::Child => {
                if let Some(parent) = tree.parent(node_index)
                    && ancestor_is_in_scope(tree, parent, scope, budget)?
                {
                    scratch.push((parent, previous_index));
                }
            }
            XPathAxis::Descendant => {
                let mut ancestor = tree.parent(node_index);
                while let Some(parent) = ancestor {
                    budget.charge()?;
                    if ancestor_is_in_scope(tree, parent, scope, budget)? {
                        scratch.push((parent, previous_index));
                    } else {
                        break;
                    }
                    if Some(parent) == scope {
                        break;
                    }
                    ancestor = tree.parent(parent);
                }
            }
        }
    }
    Ok(false)
}

fn xpath_leading_axis_matches<T: ElementTree + ?Sized>(
    tree: &T,
    node_index: usize,
    path: &XPathPath,
    scope: Option<usize>,
    budget: &mut SelectorVisitBudget,
) -> Result<bool, LocateFailure> {
    match (path.leading_axis, scope) {
        (XPathAxis::Child, Some(scope_index)) => Ok(tree.parent(node_index) == Some(scope_index)),
        (XPathAxis::Child, None) => Ok(tree.parent(node_index).is_none()),
        (XPathAxis::Descendant, Some(scope_index)) if node_index != scope_index => {
            tree.is_descendant(node_index, scope_index, budget)
        }
        (XPathAxis::Descendant, None) => Ok(true),
        _ => Ok(false),
    }
}

fn ancestor_is_in_scope<T: ElementTree + ?Sized>(
    tree: &T,
    candidate: usize,
    scope: Option<usize>,
    budget: &mut SelectorVisitBudget,
) -> Result<bool, LocateFailure> {
    match scope {
        Some(scope_index) => {
            Ok(candidate == scope_index || tree.is_descendant(candidate, scope_index, budget)?)
        }
        None => Ok(true),
    }
}

pub fn push_limited_match(
    matches: &mut Vec<usize>,
    index: usize,
    maximum: u64,
) -> Result<(), LocateFailure> {
    let count = u64::try_from(matches.len()).unwrap_or(u64::MAX);
    let observed = count
        .checked_add(1)
        .ok_or_else(|| limit_failure(ResourceLimit::Matches, maximum, u64::MAX))?;
    if observed > maximum {
        return Err(limit_failure(ResourceLimit::Matches, maximum, observed));
    }
    matches.push(index);
    Ok(())
}
