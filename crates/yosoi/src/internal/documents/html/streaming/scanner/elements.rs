use super::super::config::REPAIR_NODE_ALLOWANCE;
use super::super::names::{BASE, BODY, BR, HEAD, HTML, LINK, META, NameKey, P, TITLE};
use super::super::plan::{StreamingProjection, StreamingShape};
use super::super::routing::RelevantAttributes;
use super::super::support::TreeCoordinate;
use super::super::tag_rules::implied_close_position;
use super::super::tokenizer::{attribute, capture_value, compound_tests_match};
use super::{
    CANDIDATE_FOREIGN, CANDIDATE_TABLE, FOREIGN_CONTEXT, INSIDE_CANDIDATE, ImpliedKind,
    OpenElement, Scanner, StreamMatch, StreamValue, TagFacts,
};

impl<'source> Scanner<'source, '_> {
    #[allow(
        clippy::cognitive_complexity,
        reason = "one start-tag transition keeps ancestry, coordinates, match, repair, and budget state synchronized"
    )]
    pub(super) fn open(
        &mut self,
        name: NameKey,
        facts: TagFacts,
        attributes: &RelevantAttributes<'source>,
        source_offset: usize,
        closes_immediately: bool,
    ) -> Option<bool> {
        let parent_name = self.stack.last().map(|parent| parent.name);
        if parent_name == Some(HEAD) && !matches!(name, BASE | LINK | META | TITLE)
            || (name == HTML && parent_name.is_some())
            || (matches!(name, HEAD | BODY) && parent_name != Some(HTML))
        {
            return None;
        }
        self.add_nodes(1)?;
        self.element_upper = self.element_upper.checked_add(1)?;
        self.scan_work = self
            .scan_work
            .checked_add(attributes.source_count.checked_add(1)?)?;
        if self.scan_work > self.budget.max_selector_visits() {
            self.resource_proof_incomplete = true;
            return None;
        }
        self.max_attribute_count = self.max_attribute_count.max(attributes.source_count);
        let implies_head = name == BODY
            && self
                .stack
                .last()
                .is_some_and(|parent| parent.name == HTML && parent.child_count == 0);
        if implies_head {
            self.add_nodes(1)?;
            self.html_children.push(HEAD);
            let parent = self.stack.last_mut()?;
            parent.child_count = 1;
            let implied_depth = u64::try_from(self.stack.len()).ok()?.checked_add(1)?;
            self.max_depth = self.max_depth.max(implied_depth);
        }
        let parent_id = self.stack.last().map(|parent| parent.id);
        let ordinal = if let Some(parent) = self.stack.last_mut() {
            parent.child_count = parent.child_count.checked_add(1)?;
            parent.child_count
        } else {
            self.root_count = self.root_count.checked_add(1)?;
            self.root_count
        };
        if let Some(grid_parent) = self.grid_parent {
            if parent_id == Some(grid_parent) && !facts.leftmost {
                return None;
            }
            if facts.leftmost && parent_id != Some(grid_parent) {
                return None;
            }
        } else if facts.leftmost {
            if ordinal != 1 {
                return None;
            }
            self.grid_parent = parent_id;
        }
        self.observe_html_shell(name)?;
        let id = self.next_id;
        self.next_id = self.next_id.checked_add(1)?;
        let inherited_root = self.stack.last().map_or(0, |parent| parent.leftmost_root);
        let leftmost_root = if facts.leftmost { id } else { inherited_root };
        let candidate_root =
            facts.leftmost && compound_tests_match(attributes, &self.plan.leftmost);
        if candidate_root {
            let parent = parent_id?;
            match self.candidate_parent {
                Some(expected) if expected != parent => return None,
                None => self.candidate_parent = Some(parent),
                _ => {}
            }
            self.candidate_roots.insert(id);
        }
        let mut root_match_id = None;
        if candidate_root && self.plan.shape == StreamingShape::Root {
            if u64::try_from(self.matches.len()).ok()? >= self.budget.max_matches() {
                self.resource_proof_incomplete = true;
                return None;
            }
            let coordinate = self.coordinate_with(ordinal)?;
            self.reserve_projection(attributes)?;
            let value = capture_value(attributes, &self.plan.projection)?;
            let match_id = self.matches.len();
            let captures_text = matches!(value, StreamValue::Text { .. });
            self.matches.push(StreamMatch { coordinate, value });
            if captures_text {
                if self.active_match.is_some() {
                    return None;
                }
                self.active_match = Some(match_id);
                root_match_id = Some(match_id);
            }
        }
        let inside_candidate = candidate_root
            || self
                .stack
                .last()
                .is_some_and(|parent| parent.has_flag(INSIDE_CANDIDATE));
        if facts.foreign && !inside_candidate {
            return None;
        }
        if facts.formatting || (facts.foreign && inside_candidate) {
            self.mark_hazard((leftmost_root != 0).then_some(leftmost_root))?;
            self.add_nodes(REPAIR_NODE_ALLOWANCE)?;
        }
        let candidate_table = facts.table && inside_candidate;
        if facts.table && self.active_match.is_some() {
            return None;
        }
        if facts.table && !inside_candidate {
            return None;
        }
        if facts.table {
            self.add_nodes(4)?;
        }
        if candidate_table {
            self.table_depth = self.table_depth.checked_add(1)?;
            if leftmost_root != 0 {
                self.first_table_by_root
                    .entry(leftmost_root)
                    .or_insert(source_offset);
            }
        }
        let candidate_foreign = facts.foreign && inside_candidate;
        if candidate_foreign {
            self.foreign_depth = self.foreign_depth.checked_add(1)?;
        }
        let rightmost = facts.rightmost && compound_tests_match(attributes, &self.plan.rightmost);
        if rightmost {
            self.rightmost_match_count = self.rightmost_match_count.checked_add(1)?;
            let depth = u64::try_from(self.stack.len())
                .ok()?
                .checked_add(1)?
                .checked_add(8)?;
            self.rightmost_depth_sum_upper = self.rightmost_depth_sum_upper.checked_add(depth)?;
        }
        let relation_matches = match self.plan.shape {
            StreamingShape::Descendant => true,
            StreamingShape::Child => self
                .stack
                .last()
                .is_some_and(|parent| parent.id == leftmost_root),
            StreamingShape::Root => false,
        };
        let match_id = if inside_candidate && !candidate_root && rightmost && relation_matches {
            if self.active_match.is_some() || candidate_foreign || self.table_depth != 0 {
                return None;
            }
            let root = (leftmost_root != 0).then_some(leftmost_root)?;
            if self
                .first_table_by_root
                .get(&root)
                .is_some_and(|table| *table <= source_offset)
            {
                return None;
            }
            if u64::try_from(self.matches.len()).ok()? >= self.budget.max_matches() {
                self.resource_proof_incomplete = true;
                return None;
            }
            let coordinate = self.coordinate_with(ordinal)?;
            let id = self.matches.len();
            self.reserve_projection(attributes)?;
            let value = capture_value(attributes, &self.plan.projection)?;
            let captures_text = matches!(value, StreamValue::Text { .. });
            self.matches.push(StreamMatch { coordinate, value });
            if captures_text {
                self.active_match = Some(id);
                Some(id)
            } else {
                None
            }
        } else {
            root_match_id
        };
        let mut flags = 0_u8;
        if inside_candidate {
            flags |= INSIDE_CANDIDATE;
        }
        if candidate_table {
            flags |= CANDIDATE_TABLE;
        }
        if candidate_foreign {
            flags |= CANDIDATE_FOREIGN;
        }
        if facts.foreign {
            flags |= FOREIGN_CONTEXT;
        }
        let element = OpenElement {
            id,
            name,
            ordinal,
            child_count: 0,
            leftmost_root,
            match_id: match_id.unwrap_or(usize::MAX),
            flags,
            implied: facts.implied,
            closes_paragraph: facts.closes_paragraph,
        };
        if closes_immediately {
            self.close_element(&element)?;
        } else {
            self.stack.push(element);
            self.max_depth = self.max_depth.max(u64::try_from(self.stack.len()).ok()?);
            if self.max_depth > u64::from(self.budget.max_depth()) {
                self.resource_proof_incomplete = true;
                return None;
            }
        }
        let root_without_text = self.plan.shape == StreamingShape::Root
            && !matches!(self.plan.projection, StreamingProjection::Text);
        Some(facts.leftmost && (!candidate_root || root_without_text))
    }

    fn coordinate_with(&self, ordinal: u32) -> Option<TreeCoordinate> {
        let mut path = self
            .stack
            .iter()
            .map(|element| element.ordinal)
            .collect::<Vec<_>>();
        path.push(ordinal);
        TreeCoordinate::try_new(path, None).ok()
    }

    pub(super) fn close(
        &mut self,
        name: NameKey,
        facts: TagFacts,
        source_offset: usize,
    ) -> Option<()> {
        let position = self.stack.iter().rposition(|element| element.name == name);
        let Some(position) = position else {
            if matches!(name, BR | P) {
                let empty = RelevantAttributes::empty();
                let _ = self.open(name, facts, &empty, source_offset, true)?;
            } else if facts.formatting {
                let root = self
                    .stack
                    .last()
                    .map(|element| element.leftmost_root)
                    .filter(|root| *root != 0);
                self.mark_hazard(root)?;
            }
            return Some(());
        };
        if position.checked_add(1)? != self.stack.len() {
            let root = self
                .stack
                .get(position)
                .map(|element| element.leftmost_root)
                .filter(|root| *root != 0);
            self.mark_hazard(root)?;
            if matches!(name, BR | P) {
                return None;
            }
        }
        while self.stack.len() > position {
            let element = self.stack.pop()?;
            self.close_element(&element)?;
        }
        Some(())
    }

    pub(super) fn apply_implied_closes(
        &mut self,
        new_kind: ImpliedKind,
        closes_paragraph: bool,
    ) -> Option<()> {
        let position = implied_close_position(&self.stack, new_kind, closes_paragraph);
        let Some(position) = position else {
            return Some(());
        };
        let root = self
            .stack
            .get(position)
            .map(|element| element.leftmost_root)
            .filter(|root| *root != 0);
        self.mark_hazard(root)?;
        while self.stack.len() > position {
            let element = self.stack.pop()?;
            self.close_element(&element)?;
        }
        Some(())
    }

    fn close_element(&mut self, element: &OpenElement) -> Option<()> {
        if element.match_id != usize::MAX {
            let match_id = element.match_id;
            (self.active_match == Some(match_id)).then_some(())?;
            self.active_match = None;
        }
        if element.has_flag(CANDIDATE_TABLE) {
            self.table_depth = self.table_depth.checked_sub(1)?;
        }
        if element.has_flag(CANDIDATE_FOREIGN) {
            self.foreign_depth = self.foreign_depth.checked_sub(1)?;
        }
        Some(())
    }

    fn reserve_projection(&mut self, attributes: &RelevantAttributes<'_>) -> Option<()> {
        let bytes = match &self.plan.projection {
            StreamingProjection::Text | StreamingProjection::Node => 0,
            StreamingProjection::Attribute { key, name } => u64::try_from(name.len())
                .ok()?
                .checked_add(u64::try_from(attribute(attributes, *key)?.len()).ok()?)?,
        };
        let observed = self.projected_value_bytes.checked_add(bytes)?;
        if observed > self.budget.max_output_bytes() {
            self.resource_proof_incomplete = true;
            return None;
        }
        self.projected_value_bytes = observed;
        Some(())
    }

    fn observe_html_shell(&mut self, name: NameKey) -> Option<()> {
        match self.stack.last().map(|parent| parent.name) {
            None => {
                if name != HTML || self.root_count != 1 {
                    return None;
                }
            }
            Some(parent) if parent == HTML => self.html_children.push(name),
            _ => {}
        }
        Some(())
    }

    fn mark_hazard(&mut self, root: Option<u64>) -> Option<()> {
        let root = root?;
        self.hazard_roots.insert(root);
        Some(())
    }
}
