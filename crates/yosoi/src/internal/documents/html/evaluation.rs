use crate::internal::documents::region_membership::{region_output_failure, reserve_region_bytes};
use crate::internal::documents::{
    Completeness, DocumentClass, Finding, LocateFailure, LocateOutcome, LocateResult,
    LocateResultError, NativeCoordinate, NodeReference, Plan, ProjectedValue, Projection, RegionId,
    RegionLineage, ResourceBudget, ResourceLimit, TreeCoordinate,
};

use super::output_size::finding_output_bytes;
use super::{
    CompiledTreeOutput, CompiledTreePlan, ParsedHtmlDocument, SelectorVisitBudget,
    canonical_attribute_name, element_attribute, invalid_failure, invalid_plan, limit_failure,
};

impl ParsedHtmlDocument {
    /// Evaluates one portable plan in parser document order.
    #[allow(clippy::manual_let_else)] // Overflow branches preserve stable failure codes.
    pub(in crate::internal::documents) fn locate_with_budget(
        &self,
        plan: &Plan,
        budget: ResourceBudget,
    ) -> LocateOutcome {
        if !plan.requirement().accepts(DocumentClass::SourceHtml) {
            return LocateOutcome::Failed {
                failure: LocateFailure::UnsupportedCombination {
                    document: DocumentClass::SourceHtml,
                },
            };
        }
        let limits = budget;
        if self.input_bytes > limits.max_input_bytes() {
            return LocateOutcome::Failed {
                failure: limit_failure(
                    ResourceLimit::InputBytes,
                    limits.max_input_bytes(),
                    self.input_bytes,
                ),
            };
        }
        if self.tree.node_count() > limits.max_nodes() {
            return LocateOutcome::Failed {
                failure: limit_failure(
                    ResourceLimit::Nodes,
                    limits.max_nodes(),
                    self.tree.node_count(),
                ),
            };
        }
        if self.tree.max_depth() > limits.max_depth() {
            return LocateOutcome::Failed {
                failure: limit_failure(
                    ResourceLimit::Depth,
                    u64::from(limits.max_depth()),
                    u64::from(self.tree.max_depth()),
                ),
            };
        }

        let compiled: &CompiledTreePlan = match plan.compiled_tree_plan(budget) {
            Ok(compiled) => compiled,
            Err(failure) => return LocateOutcome::Failed { failure },
        };
        let mut selector_budget = SelectorVisitBudget::new(limits.max_selector_visits());
        let mut region_results = Vec::<(RegionId, Vec<usize>)>::new();
        let mut region_match_count = 0_u64;
        for region in &compiled.regions {
            let remaining_matches = limits.max_matches().saturating_sub(region_match_count);
            let matches =
                match self.select(&region.query, None, remaining_matches, &mut selector_budget) {
                    Ok(matches) => matches,
                    Err(failure) => return LocateOutcome::Failed { failure },
                };
            let observed_region_matches =
                region_match_count.saturating_add(u64::try_from(matches.len()).unwrap_or(u64::MAX));
            if observed_region_matches > limits.max_matches() {
                return LocateOutcome::Failed {
                    failure: limit_failure(
                        ResourceLimit::Matches,
                        limits.max_matches(),
                        observed_region_matches,
                    ),
                };
            }
            region_match_count = observed_region_matches;
            region_results.push((region.id.clone(), matches));
        }

        let mut matched_regions = Vec::new();
        let mut output_bytes = 0_u64;
        for (region_id, nodes) in &region_results {
            for (region_index, region_node) in nodes.iter().copied().enumerate() {
                let Some(region_coordinate) = self.coordinate(region_node) else {
                    return invalid_plan("html_coordinate_invalid");
                };
                let region_ordinal = match u64::try_from(region_index)
                    .ok()
                    .and_then(|index| index.checked_add(1))
                {
                    Some(ordinal) => ordinal,
                    None => return invalid_plan("html_region_ordinal_overflow"),
                };
                let lineage = RegionLineage::new(
                    region_id.clone(),
                    region_ordinal,
                    NativeCoordinate::SourceTree(region_coordinate),
                );
                if let Err(error) =
                    reserve_region_bytes(&mut output_bytes, limits.max_output_bytes(), &lineage)
                {
                    return LocateOutcome::Failed {
                        failure: region_output_failure(
                            error,
                            limits.max_output_bytes(),
                            "html_region_output_size_invalid",
                        ),
                    };
                }
                matched_regions.push(lineage);
            }
        }

        let mut findings = Vec::new();
        let mut next_order = 0_u64;
        for output in &compiled.outputs {
            if let Some(region_id) = &output.parent_region {
                let Some((_, regions)) = region_results
                    .iter()
                    .find(|(candidate, _)| candidate == region_id)
                else {
                    return invalid_plan("html_region_not_found");
                };
                for (region_index, region_node) in regions.iter().copied().enumerate() {
                    let Some(region_coordinate) = self.coordinate(region_node) else {
                        return invalid_plan("html_coordinate_invalid");
                    };
                    let region_ordinal = match u64::try_from(region_index)
                        .ok()
                        .and_then(|index| index.checked_add(1))
                    {
                        Some(ordinal) => ordinal,
                        None => return invalid_plan("html_region_ordinal_overflow"),
                    };
                    let lineage = RegionLineage::new(
                        region_id.clone(),
                        region_ordinal,
                        NativeCoordinate::SourceTree(region_coordinate),
                    );
                    let matches = match self.select(
                        &output.query,
                        Some(region_node),
                        limits.max_matches(),
                        &mut selector_budget,
                    ) {
                        Ok(matches) => matches,
                        Err(failure) => return LocateOutcome::Failed { failure },
                    };
                    for matched_node in matches {
                        if let Err(failure) = self.push_finding(
                            &mut findings,
                            &mut next_order,
                            &mut output_bytes,
                            limits,
                            output,
                            matched_node,
                            Some(lineage.clone()),
                            &mut selector_budget,
                        ) {
                            return LocateOutcome::Failed { failure };
                        }
                    }
                }
            } else {
                let matches = match self.select(
                    &output.query,
                    None,
                    limits.max_matches(),
                    &mut selector_budget,
                ) {
                    Ok(matches) => matches,
                    Err(failure) => return LocateOutcome::Failed { failure },
                };
                for matched_node in matches {
                    if let Err(failure) = self.push_finding(
                        &mut findings,
                        &mut next_order,
                        &mut output_bytes,
                        limits,
                        output,
                        matched_node,
                        None,
                        &mut selector_budget,
                    ) {
                        return LocateOutcome::Failed { failure };
                    }
                }
            }
        }

        if findings.is_empty() && matched_regions.is_empty() {
            return LocateOutcome::NoMatch {
                document_id: self.document_id.clone(),
            };
        }
        match LocateResult::try_new_with_regions(
            self.document_id.clone(),
            matched_regions,
            findings,
        ) {
            Ok(result) => LocateOutcome::Matched { result },
            Err(LocateResultError::Empty) => invalid_plan("html_empty_result"),
            Err(LocateResultError::DocumentMismatch) => {
                invalid_plan("html_result_document_mismatch")
            }
            Err(LocateResultError::NonDeterministicOrder) => {
                invalid_plan("html_result_order_invalid")
            }
            Err(LocateResultError::DuplicateRegion) => {
                invalid_plan("html_result_region_duplicated")
            }
            Err(LocateResultError::UnknownParentRegion) => {
                invalid_plan("html_result_parent_region_unknown")
            }
        }
    }

    #[allow(clippy::too_many_arguments)] // Explicit plan-wide counters share one budget.
    fn push_finding(
        &self,
        findings: &mut Vec<Finding>,
        next_order: &mut u64,
        output_bytes: &mut u64,
        limits: ResourceBudget,
        output: &CompiledTreeOutput,
        matched_node: usize,
        parent_region: Option<RegionLineage>,
        budget: &mut SelectorVisitBudget,
    ) -> Result<(), LocateFailure> {
        let count = u64::try_from(findings.len()).unwrap_or(u64::MAX);
        let observed_matches = count
            .checked_add(1)
            .ok_or_else(|| limit_failure(ResourceLimit::Matches, limits.max_matches(), u64::MAX))?;
        if observed_matches > limits.max_matches() {
            return Err(limit_failure(
                ResourceLimit::Matches,
                limits.max_matches(),
                observed_matches,
            ));
        }
        let coordinate = self
            .coordinate(matched_node)
            .ok_or_else(|| invalid_failure("html_coordinate_invalid"))?;
        let value = self
            .project(matched_node, &coordinate, &output.projection, budget)?
            .ok_or_else(|| invalid_failure("html_projection_invalid"))?;
        let added_bytes = finding_output_bytes(
            &self.document_id,
            &output.id,
            &coordinate,
            &value,
            parent_region.as_ref(),
        )
        .ok_or_else(|| {
            limit_failure(
                ResourceLimit::OutputBytes,
                limits.max_output_bytes(),
                u64::MAX,
            )
        })?;
        let observed_bytes = output_bytes.checked_add(added_bytes).ok_or_else(|| {
            limit_failure(
                ResourceLimit::OutputBytes,
                limits.max_output_bytes(),
                u64::MAX,
            )
        })?;
        if observed_bytes > limits.max_output_bytes() {
            return Err(limit_failure(
                ResourceLimit::OutputBytes,
                limits.max_output_bytes(),
                observed_bytes,
            ));
        }
        let order = *next_order;
        let next = order
            .checked_add(1)
            .ok_or_else(|| invalid_failure("html_result_order_overflow"))?;
        let finding = Finding::try_new(
            self.document_id.clone(),
            output.id.clone(),
            order,
            NativeCoordinate::SourceTree(coordinate),
            value,
            Completeness::Complete,
            parent_region,
        )
        .map_err(|_| invalid_failure("html_finding_invalid"))?;
        findings.push(finding);
        *next_order = next;
        *output_bytes = observed_bytes;
        Ok(())
    }

    fn project(
        &self,
        element_index: usize,
        coordinate: &TreeCoordinate,
        projection: &Projection,
        budget: &mut SelectorVisitBudget,
    ) -> Result<Option<ProjectedValue>, LocateFailure> {
        match projection {
            Projection::DescendantText => {
                if self.tree.element(element_index).is_none() {
                    return Ok(None);
                }
                let text_index = self
                    .text_index()
                    .map_err(|error| super::parse_failure(&error))?;
                let text = match text_index.range(element_index) {
                    Some((start, end)) => match text_index.normalized().get(start..end) {
                        Some(text) => text.trim_matches(' ').to_owned(),
                        None => return Ok(None),
                    },
                    None => String::new(),
                };
                Ok(Some(ProjectedValue::Text(text)))
            }
            Projection::Attribute(name) => {
                let Some(element) = self.tree.element(element_index) else {
                    return Ok(None);
                };
                let Some(value) = element_attribute(element, name, budget)? else {
                    return Ok(None);
                };
                Ok(Some(ProjectedValue::Attribute {
                    name: canonical_attribute_name(element, name),
                    value,
                }))
            }
            Projection::NodeReference => Ok(Some(ProjectedValue::Node(NodeReference::new(
                self.document_id.clone(),
                NativeCoordinate::SourceTree(coordinate.clone()),
            )))),
            Projection::JsonValue
            | Projection::AccessibleName
            | Projection::AccessibilityText
            | Projection::MatchedText
            | Projection::MatchedTextWithCaptures { .. } => Ok(None),
        }
    }

    fn coordinate(&self, element_index: usize) -> Option<TreeCoordinate> {
        let mut path = Vec::new();
        let mut current = Some(element_index);
        while let Some(index) = current {
            let element = self.tree.element(index)?;
            path.push(element.element_sibling_ordinal()?);
            current = element.element_parent();
        }
        if path.is_empty() {
            return None;
        }
        path.reverse();
        TreeCoordinate::try_new(path, None).ok()
    }
}
