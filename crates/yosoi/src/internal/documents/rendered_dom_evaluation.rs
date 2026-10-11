#[path = "rendered_dom_evaluation/byte_accounting.rs"]
mod byte_accounting;

use byte_accounting::finding_output_bytes;

use super::super::html::{
    CompiledTreeOutput, SelectorVisitBudget, TreeQuery, canonical_attribute_name,
    element_attribute, invalid_failure, invalid_plan, limit_failure, select_tree,
};
use super::super::region_membership::{region_output_failure, reserve_region_bytes};
use super::super::{
    Completeness, DocumentClass, DomCoordinate, Finding, LocateFailure, LocateOutcome,
    LocateResult, LocateResultError, NativeCoordinate, NodeReference, Plan, ProjectedValue,
    Projection, RegionId, RegionLineage, ResourceBudget, ResourceLimit,
};

use super::types::RenderedDomDocument;

impl RenderedDomDocument {
    /// Evaluates one portable plan in canonical rendered-DOM preorder.
    #[allow(clippy::manual_let_else)] // Overflow branches preserve stable failure codes.
    pub(in crate::internal::documents) fn locate_with_budget(
        &self,
        plan: &Plan,
        budget: ResourceBudget,
    ) -> LocateOutcome {
        if !plan.requirement().accepts(DocumentClass::RenderedDom) {
            return LocateOutcome::Failed {
                failure: LocateFailure::UnsupportedCombination {
                    document: DocumentClass::RenderedDom,
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
        if self.node_count > limits.max_nodes() {
            return LocateOutcome::Failed {
                failure: limit_failure(ResourceLimit::Nodes, limits.max_nodes(), self.node_count),
            };
        }
        if self.max_depth > limits.max_depth() {
            return LocateOutcome::Failed {
                failure: limit_failure(
                    ResourceLimit::Depth,
                    u64::from(limits.max_depth()),
                    u64::from(self.max_depth),
                ),
            };
        }

        let compiled = match plan.compiled_tree_plan(budget) {
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
            let observed =
                region_match_count.saturating_add(u64::try_from(matches.len()).unwrap_or(u64::MAX));
            if observed > limits.max_matches() {
                return LocateOutcome::Failed {
                    failure: limit_failure(ResourceLimit::Matches, limits.max_matches(), observed),
                };
            }
            region_match_count = observed;
            region_results.push((region.id.clone(), matches));
        }

        let mut matched_regions = Vec::new();
        let mut output_bytes = 0_u64;
        for (region_id, nodes) in &region_results {
            for (region_index, region_node) in nodes.iter().copied().enumerate() {
                let Some(region_coordinate) = self.coordinate(region_node) else {
                    return invalid_plan("rendered_dom_coordinate_invalid");
                };
                let region_ordinal = match u64::try_from(region_index)
                    .ok()
                    .and_then(|index| index.checked_add(1))
                {
                    Some(ordinal) => ordinal,
                    None => return invalid_plan("rendered_dom_region_ordinal_overflow"),
                };
                let lineage = RegionLineage::new(
                    region_id.clone(),
                    region_ordinal,
                    NativeCoordinate::RenderedDom(region_coordinate),
                );
                if let Err(error) =
                    reserve_region_bytes(&mut output_bytes, limits.max_output_bytes(), &lineage)
                {
                    return LocateOutcome::Failed {
                        failure: region_output_failure(
                            error,
                            limits.max_output_bytes(),
                            "rendered_dom_region_output_size_invalid",
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
                    return invalid_plan("rendered_dom_region_not_found");
                };
                for (region_index, region_node) in regions.iter().copied().enumerate() {
                    let Some(region_coordinate) = self.coordinate(region_node) else {
                        return invalid_plan("rendered_dom_coordinate_invalid");
                    };
                    let region_ordinal = match u64::try_from(region_index)
                        .ok()
                        .and_then(|index| index.checked_add(1))
                    {
                        Some(ordinal) => ordinal,
                        None => return invalid_plan("rendered_dom_region_ordinal_overflow"),
                    };
                    let lineage = RegionLineage::new(
                        region_id.clone(),
                        region_ordinal,
                        NativeCoordinate::RenderedDom(region_coordinate),
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
            Err(LocateResultError::Empty) => invalid_plan("rendered_dom_empty_result"),
            Err(LocateResultError::DocumentMismatch) => {
                invalid_plan("rendered_dom_result_document_mismatch")
            }
            Err(LocateResultError::NonDeterministicOrder) => {
                invalid_plan("rendered_dom_result_order_invalid")
            }
            Err(LocateResultError::DuplicateRegion) => {
                invalid_plan("rendered_dom_result_region_duplicated")
            }
            Err(LocateResultError::UnknownParentRegion) => {
                invalid_plan("rendered_dom_result_parent_region_unknown")
            }
        }
    }

    fn select(
        &self,
        query: &TreeQuery,
        scope: Option<usize>,
        maximum: u64,
        budget: &mut SelectorVisitBudget,
    ) -> Result<Vec<usize>, LocateFailure> {
        select_tree(
            self.elements.as_slice(),
            &self.normalized_text,
            &self.text_segments,
            query,
            scope,
            maximum,
            budget,
        )
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
            .ok_or_else(|| invalid_failure("rendered_dom_coordinate_invalid"))?;
        let value = self
            .project(matched_node, &coordinate, &output.projection, budget)?
            .ok_or_else(|| invalid_failure("rendered_dom_projection_invalid"))?;
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
            .ok_or_else(|| invalid_failure("rendered_dom_result_order_overflow"))?;
        let finding = Finding::try_new(
            self.document_id.clone(),
            output.id.clone(),
            order,
            NativeCoordinate::RenderedDom(coordinate),
            value,
            Completeness::Complete,
            parent_region,
        )
        .map_err(|_| invalid_failure("rendered_dom_finding_invalid"))?;
        findings.push(finding);
        *next_order = next;
        *output_bytes = observed_bytes;
        Ok(())
    }

    fn project(
        &self,
        element_index: usize,
        coordinate: &DomCoordinate,
        projection: &Projection,
        budget: &mut SelectorVisitBudget,
    ) -> Result<Option<ProjectedValue>, LocateFailure> {
        match projection {
            Projection::DescendantText => {
                let Some(element) = self.elements.get(element_index) else {
                    return Ok(None);
                };
                let text = match element.text_range {
                    Some((start, end)) => match self.normalized_text.get(start..end) {
                        Some(text) => text.trim_matches(' ').to_owned(),
                        None => return Ok(None),
                    },
                    None => String::new(),
                };
                Ok(Some(ProjectedValue::Text(text)))
            }
            Projection::Attribute(name) => {
                let Some(element) = self.elements.get(element_index) else {
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
                NativeCoordinate::RenderedDom(*coordinate),
            )))),
            Projection::JsonValue
            | Projection::AccessibleName
            | Projection::AccessibilityText
            | Projection::MatchedText
            | Projection::MatchedTextWithCaptures { .. } => Ok(None),
        }
    }

    fn coordinate(&self, element_index: usize) -> Option<DomCoordinate> {
        let element = self.elements.get(element_index)?;
        Some(DomCoordinate::new(self.document_epoch, element.id))
    }
}
