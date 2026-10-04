use roxmltree::Node;

use crate::{
    ByteRange, Completeness, DocumentClass, ExpandedNamePathSegment, Finding, LocateFailure,
    LocateOutcome, LocateResult, NativeCoordinate, NodeReference, Plan, ProjectedValue,
    RegionLineage, ResourceBudget, ResourceLimit, TreeCoordinate,
};

use super::output::serialized_size;
use super::query::{CompiledXmlProjection, CompiledXmlQuery};
use super::region_evaluation::collect_region_memberships;
use super::text::{descendant_text, select_tree_text};
use super::{QueryWorkBudget, XmlDocument, XmlError};

impl<'input> XmlDocument<'input> {
    /// Evaluates all outputs into one globally ordered plan outcome.
    pub(crate) fn locate_with_budget(&self, plan: &Plan, budget: ResourceBudget) -> LocateOutcome {
        match self.locate_checked(plan, budget) {
            Ok(outcome) => outcome,
            Err(error) => LocateOutcome::Failed {
                failure: evaluation_failure(&error),
            },
        }
    }

    fn locate_checked(
        &self,
        plan: &Plan,
        budget: ResourceBudget,
    ) -> Result<LocateOutcome, XmlError> {
        if !plan.requirement().accepts(crate::DocumentClass::SourceXml) {
            return Err(XmlError::IncompatiblePlan);
        }
        if self.document.byte_len() > budget.max_input_bytes() {
            return Err(XmlError::InputLimitExceeded {
                maximum: budget.max_input_bytes(),
                observed: self.document.byte_len(),
            });
        }
        if self.node_count > budget.max_nodes() {
            return Err(XmlError::NodeLimitExceeded {
                maximum: budget.max_nodes(),
                observed: self.node_count,
            });
        }
        if self.depth > budget.max_depth() {
            return Err(XmlError::DepthLimitExceeded {
                maximum: budget.max_depth(),
                observed: self.depth,
            });
        }

        let compiled_plan = plan.compiled_xml_plan(budget)?;
        let mut findings = Vec::new();
        let mut next_order = 0_u64;
        let mut total_matches = 0_u64;
        let mut total_output_bytes = 0_u64;
        let mut work_budget = QueryWorkBudget::new(budget.max_selector_visits());
        let (region_results, matched_regions) = collect_region_memberships(
            self,
            plan,
            compiled_plan,
            budget,
            &mut work_budget,
            &mut total_output_bytes,
        )?;
        for (output_index, output) in plan.outputs().iter().enumerate() {
            let (query, projection) = compiled_plan.output(output_index)?;
            if let Some(region_id) = output.parent_region() {
                let (_, regions) = region_results
                    .iter()
                    .find(|(candidate, _)| candidate == region_id)
                    .ok_or(XmlError::InvalidResult)?;
                for (region_node, lineage) in regions {
                    let field_nodes = self.select(query, *region_node, budget, &mut work_budget)?;
                    self.append_findings(
                        &mut findings,
                        &mut next_order,
                        &mut total_matches,
                        output,
                        projection,
                        field_nodes,
                        Some(lineage.clone()),
                        &mut total_output_bytes,
                        &mut work_budget,
                        budget,
                    )?;
                }
            } else {
                let nodes = self.select(query, self.tree.root(), budget, &mut work_budget)?;
                self.append_findings(
                    &mut findings,
                    &mut next_order,
                    &mut total_matches,
                    output,
                    projection,
                    nodes,
                    None,
                    &mut total_output_bytes,
                    &mut work_budget,
                    budget,
                )?;
            }
        }
        let outcome = if findings.is_empty() && matched_regions.is_empty() {
            LocateOutcome::NoMatch {
                document_id: self.document.id().clone(),
            }
        } else {
            let result = LocateResult::try_new_with_regions(
                self.document.id().clone(),
                matched_regions,
                findings,
            )
            .map_err(|_| XmlError::InvalidResult)?;
            LocateOutcome::Matched { result }
        };
        let observed_output_bytes = serialized_size(&outcome)?;
        if observed_output_bytes > budget.max_output_bytes() {
            return Err(XmlError::OutputLimitExceeded {
                maximum: budget.max_output_bytes(),
                observed: observed_output_bytes,
            });
        }
        Ok(outcome)
    }

    pub(super) fn select<'tree>(
        &'tree self,
        query: &CompiledXmlQuery,
        context: Node<'tree, 'input>,
        limits: ResourceBudget,
        work_budget: &mut QueryWorkBudget,
    ) -> Result<Vec<Node<'tree, 'input>>, XmlError> {
        let max_matches = limits.max_matches();
        match query {
            CompiledXmlQuery::Css(selector) => selector.evaluate(context, max_matches, work_budget),
            CompiledXmlQuery::XPath(xpath) => {
                xpath.evaluate(&self.tree, context, max_matches, work_budget)
            }
            CompiledXmlQuery::TreeTextContains(needle) => {
                select_tree_text(context, needle, max_matches, work_budget)
            }
        }
    }

    #[allow(
        clippy::too_many_arguments,
        clippy::needless_pass_by_value,
        clippy::option_if_let_else
    )]
    // Explicit counters and owned lineage preserve one bounded output transaction.
    fn append_findings(
        &self,
        findings: &mut Vec<Finding>,
        next_order: &mut u64,
        total_matches: &mut u64,
        output: &crate::CompiledOutput,
        projection: &CompiledXmlProjection,
        nodes: Vec<Node<'_, 'input>>,
        parent_region: Option<RegionLineage>,
        total_output_bytes: &mut u64,
        work_budget: &mut QueryWorkBudget,
        limits: ResourceBudget,
    ) -> Result<(), XmlError> {
        for node in nodes {
            *total_matches = total_matches
                .checked_add(1)
                .ok_or(XmlError::InvalidResult)?;
            if *total_matches > limits.max_matches() {
                return Err(XmlError::MatchLimitExceeded {
                    maximum: limits.max_matches(),
                    observed: *total_matches,
                });
            }

            let coordinate = NativeCoordinate::SourceTree(self.coordinate(node, work_budget)?);
            let value = match projection {
                CompiledXmlProjection::DescendantText => {
                    ProjectedValue::Text(descendant_text(node, work_budget)?)
                }
                CompiledXmlProjection::Attribute {
                    namespace_uri,
                    local_name,
                    canonical_name,
                } => {
                    let mut projected_attribute = None;
                    for attribute in node.attributes() {
                        work_budget.visit()?;
                        if attribute.name() == local_name.as_str()
                            && attribute.namespace() == namespace_uri.as_deref()
                        {
                            projected_attribute = Some(attribute.value().to_owned());
                            break;
                        }
                    }
                    let projected_attribute =
                        projected_attribute.ok_or(XmlError::MissingProjectedAttribute)?;
                    ProjectedValue::Attribute {
                        name: canonical_name.clone(),
                        value: projected_attribute,
                    }
                }
                CompiledXmlProjection::NodeReference => ProjectedValue::Node(NodeReference::new(
                    self.document.id().clone(),
                    coordinate.clone(),
                )),
            };
            let order = *next_order;
            *next_order = next_order.checked_add(1).ok_or(XmlError::InvalidResult)?;
            let finding = Finding::try_new(
                self.document.id().clone(),
                output.id().clone(),
                order,
                coordinate,
                value,
                Completeness::Complete,
                parent_region.clone(),
            )
            .map_err(|_| XmlError::InvalidResult)?;
            let finding_bytes = serialized_size(&finding)?;
            *total_output_bytes = total_output_bytes
                .checked_add(finding_bytes)
                .ok_or(XmlError::InvalidResult)?;
            if *total_output_bytes > limits.max_output_bytes() {
                return Err(XmlError::OutputLimitExceeded {
                    maximum: limits.max_output_bytes(),
                    observed: *total_output_bytes,
                });
            }
            findings.push(finding);
        }
        Ok(())
    }

    #[allow(clippy::unused_self)] // Kept beside evaluation for representation-local semantics.
    pub(super) fn coordinate(
        &self,
        node: Node<'_, 'input>,
        work_budget: &mut QueryWorkBudget,
    ) -> Result<TreeCoordinate, XmlError> {
        let mut path = Vec::<ExpandedNamePathSegment>::new();
        let mut child_path = Vec::<u32>::new();
        let mut current = Some(node);
        while let Some(element) = current.filter(roxmltree::Node::is_element) {
            let name = element.tag_name();
            let mut same_name_index = 0_u32;
            let mut child_index = 0_u32;
            if let Some(parent) = element.parent() {
                for sibling in parent.children().filter(Node::is_element) {
                    work_budget.visit()?;
                    child_index = child_index.checked_add(1).ok_or(XmlError::InvalidResult)?;
                    let sibling_name = sibling.tag_name();
                    if sibling_name.namespace() == name.namespace()
                        && sibling_name.name() == name.name()
                    {
                        same_name_index = same_name_index
                            .checked_add(1)
                            .ok_or(XmlError::InvalidResult)?;
                    }
                    if sibling.id() == element.id() {
                        break;
                    }
                }
            }
            if same_name_index == 0 || child_index == 0 {
                return Err(XmlError::InvalidResult);
            }
            path.push(
                ExpandedNamePathSegment::try_new(
                    name.namespace().map(str::to_owned),
                    name.name(),
                    same_name_index,
                )
                .map_err(|_| XmlError::InvalidResult)?,
            );
            child_path.push(child_index);
            current = element.parent();
        }
        path.reverse();
        child_path.reverse();
        let range = node.range();
        let source_range = ByteRange::try_new(
            u64::try_from(range.start).map_err(|_| XmlError::InvalidResult)?,
            u64::try_from(range.end).map_err(|_| XmlError::InvalidResult)?,
        )
        .map_err(|_| XmlError::InvalidResult)?;
        TreeCoordinate::with_expanded_name_path(child_path, Some(source_range), path)
            .map_err(|_| XmlError::InvalidResult)
    }
}

pub(super) fn evaluation_failure(error: &XmlError) -> LocateFailure {
    match error {
        XmlError::WrongDocumentClass { actual } => {
            LocateFailure::UnsupportedCombination { document: *actual }
        }
        XmlError::InputLimitExceeded { maximum, observed } => LocateFailure::LimitExhausted {
            limit: ResourceLimit::InputBytes,
            maximum: *maximum,
            observed: *observed,
        },
        XmlError::NodeLimitExceeded { maximum, observed } => LocateFailure::LimitExhausted {
            limit: ResourceLimit::Nodes,
            maximum: *maximum,
            observed: *observed,
        },
        XmlError::DepthLimitExceeded { maximum, observed } => LocateFailure::LimitExhausted {
            limit: ResourceLimit::Depth,
            maximum: u64::from(*maximum),
            observed: u64::from(*observed),
        },
        XmlError::QueryStepLimitExceeded { maximum, observed } => LocateFailure::LimitExhausted {
            limit: ResourceLimit::QuerySteps,
            maximum: u64::from(*maximum),
            observed: u64::from(*observed),
        },
        XmlError::TraversalLimitExceeded { maximum, observed } => LocateFailure::LimitExhausted {
            limit: ResourceLimit::SelectorVisits,
            maximum: *maximum,
            observed: *observed,
        },
        XmlError::MatchLimitExceeded { maximum, observed } => LocateFailure::LimitExhausted {
            limit: ResourceLimit::Matches,
            maximum: *maximum,
            observed: *observed,
        },
        XmlError::OutputLimitExceeded { maximum, observed } => LocateFailure::LimitExhausted {
            limit: ResourceLimit::OutputBytes,
            maximum: *maximum,
            observed: *observed,
        },
        XmlError::InvalidUtf8 => LocateFailure::ParseFailed {
            code: "xml_invalid_utf8".to_owned(),
        },
        XmlError::DtdProhibited => LocateFailure::ParseFailed {
            code: "xml_dtd_prohibited".to_owned(),
        },
        XmlError::MalformedXml => LocateFailure::ParseFailed {
            code: "xml_malformed".to_owned(),
        },
        XmlError::NodeCountOverflow => LocateFailure::ParseFailed {
            code: "xml_node_count_overflow".to_owned(),
        },
        XmlError::IncompatiblePlan => LocateFailure::UnsupportedCombination {
            document: DocumentClass::SourceXml,
        },
        XmlError::InvalidQuery => LocateFailure::InvalidPlan {
            code: "xml_invalid_query".to_owned(),
        },
        XmlError::UnboundNamespacePrefix => LocateFailure::InvalidPlan {
            code: "xml_unbound_namespace_prefix".to_owned(),
        },
        XmlError::MissingProjectedAttribute => LocateFailure::InvalidPlan {
            code: "xml_missing_projected_attribute".to_owned(),
        },
        XmlError::InvalidResult => LocateFailure::InvalidPlan {
            code: "xml_invalid_result".to_owned(),
        },
    }
}
