use std::io::{self, Write};

use crate::{
    AccessibilityCoordinate, Finding, LocateFailure, LocateOutcome, LocateResult,
    LocateResultError, NativeCoordinate, NodeReference, Plan, ProjectedValue, Projection,
    QueryAtom, ResourceBudget, ResourceLimit,
};

use super::types::{AccessibilityNode, ParsedAccessibilityDocument, parse_failure};

impl ParsedAccessibilityDocument {
    /// Evaluates a compiled AX-only plan in tree preorder and output order.
    #[allow(clippy::manual_let_else)] // Early typed-failure returns keep budgets explicit.
    pub(crate) fn locate_with_budget(&self, plan: &Plan, budget: ResourceBudget) -> LocateOutcome {
        if !plan
            .requirement()
            .accepts(crate::DocumentClass::AccessibilityTree)
        {
            return LocateOutcome::Failed {
                failure: LocateFailure::UnsupportedCombination {
                    document: crate::DocumentClass::AccessibilityTree,
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
        if !plan.regions().is_empty() {
            return invalid_plan("accessibility_regions_unsupported");
        }

        let mut findings = Vec::new();
        let mut next_order = 0_u64;
        let mut match_count = 0_u64;
        let mut output_bytes = 0_u64;
        let mut selector_visits = 0_u64;
        for output in plan.outputs() {
            for node_index in &self.tree_order {
                if let Err(failure) =
                    charge_selector_visit(&mut selector_visits, limits.max_selector_visits())
                {
                    return LocateOutcome::Failed { failure };
                }
                let Some(node) = self.nodes.get(*node_index) else {
                    return invalid_plan("accessibility_node_index_invalid");
                };
                if !Self::matches(node, output.query().atom()) {
                    continue;
                }
                let observed_matches = match match_count.checked_add(1) {
                    Some(value) => value,
                    None => {
                        return LocateOutcome::Failed {
                            failure: limit_failure(
                                ResourceLimit::Matches,
                                limits.max_matches(),
                                u64::MAX,
                            ),
                        };
                    }
                };
                if observed_matches > limits.max_matches() {
                    return LocateOutcome::Failed {
                        failure: limit_failure(
                            ResourceLimit::Matches,
                            limits.max_matches(),
                            observed_matches,
                        ),
                    };
                }
                let coordinate =
                    match AccessibilityCoordinate::try_new(self.document_epoch, node.id.clone()) {
                        Ok(value) => value,
                        Err(_) => return invalid_plan("accessibility_coordinate_invalid"),
                    };
                let native_coordinate = NativeCoordinate::Accessibility(coordinate);
                let value = match self.project(node, &native_coordinate, output.projection()) {
                    Some(value) => value,
                    None => return invalid_plan("accessibility_projection_invalid"),
                };
                let order = next_order;
                let following_order = match order.checked_add(1) {
                    Some(value) => value,
                    None => return invalid_plan("accessibility_result_order_overflow"),
                };
                let finding = match Finding::try_new(
                    self.document_id.clone(),
                    output.id().clone(),
                    order,
                    native_coordinate,
                    value,
                    self.completeness.finding_completeness(),
                    None,
                ) {
                    Ok(value) => value,
                    Err(_) => return invalid_plan("accessibility_finding_invalid"),
                };
                let mut byte_counter = ByteCounter::default();
                if serde_json::to_writer(&mut byte_counter, &finding).is_err() {
                    return parse_failure_outcome("accessibility_output_serialization_failed");
                }
                let observed_bytes = match output_bytes.checked_add(byte_counter.bytes) {
                    Some(value) => value,
                    None => {
                        return LocateOutcome::Failed {
                            failure: limit_failure(
                                ResourceLimit::OutputBytes,
                                limits.max_output_bytes(),
                                u64::MAX,
                            ),
                        };
                    }
                };
                if observed_bytes > limits.max_output_bytes() {
                    return LocateOutcome::Failed {
                        failure: limit_failure(
                            ResourceLimit::OutputBytes,
                            limits.max_output_bytes(),
                            observed_bytes,
                        ),
                    };
                }
                findings.push(finding);
                match_count = observed_matches;
                output_bytes = observed_bytes;
                next_order = following_order;
            }
        }

        if findings.is_empty() {
            if let (Some(completeness), Some(reason_code)) = (
                self.completeness.absence_evidence(),
                self.completeness.absence_reason(),
            ) {
                return LocateOutcome::Indeterminate {
                    document_id: self.document_id.clone(),
                    completeness,
                    reason_code,
                };
            }
            return LocateOutcome::NoMatch {
                document_id: self.document_id.clone(),
            };
        }

        match LocateResult::try_new(self.document_id.clone(), findings) {
            Ok(result) => {
                let mut byte_counter = ByteCounter::default();
                if serde_json::to_writer(&mut byte_counter, &result).is_err() {
                    return parse_failure_outcome("accessibility_result_serialization_failed");
                }
                if byte_counter.bytes > limits.max_output_bytes() {
                    return LocateOutcome::Failed {
                        failure: limit_failure(
                            ResourceLimit::OutputBytes,
                            limits.max_output_bytes(),
                            byte_counter.bytes,
                        ),
                    };
                }
                LocateOutcome::Matched { result }
            }
            Err(LocateResultError::Empty) => invalid_plan("accessibility_empty_result"),
            Err(LocateResultError::DocumentMismatch) => {
                invalid_plan("accessibility_result_document_mismatch")
            }
            Err(LocateResultError::NonDeterministicOrder) => {
                invalid_plan("accessibility_result_order_invalid")
            }
            Err(LocateResultError::DuplicateRegion) => {
                invalid_plan("accessibility_result_region_duplicated")
            }
            Err(LocateResultError::UnknownParentRegion) => {
                invalid_plan("accessibility_result_parent_region_unknown")
            }
        }
    }

    fn matches(node: &AccessibilityNode, atom: &QueryAtom) -> bool {
        if node.ignored {
            return false;
        }
        match atom {
            QueryAtom::AccessibilityRole(expected) => node.role.as_str() == expected.as_str(),
            QueryAtom::AccessibleName(expected) => {
                node.accessible_name.as_deref() == Some(expected.as_str())
            }
            QueryAtom::AccessibilityText(expected) => {
                node.text.as_deref() == Some(expected.as_str())
            }
            QueryAtom::AccessibilityState { name, value } => node
                .states
                .get(name)
                .is_some_and(|observed| observed == value),
            _ => false,
        }
    }

    fn project(
        &self,
        node: &AccessibilityNode,
        coordinate: &NativeCoordinate,
        projection: &Projection,
    ) -> Option<ProjectedValue> {
        match projection {
            Projection::NodeReference => Some(ProjectedValue::Node(NodeReference::new(
                self.document_id.clone(),
                coordinate.clone(),
            ))),
            Projection::AccessibleName => node.accessible_name.clone().map(ProjectedValue::Text),
            Projection::AccessibilityText => node.text.clone().map(ProjectedValue::Text),
            Projection::DescendantText
            | Projection::Attribute(_)
            | Projection::JsonValue
            | Projection::MatchedText
            | Projection::MatchedTextWithCaptures { .. } => None,
        }
    }
}

#[derive(Default)]
struct ByteCounter {
    bytes: u64,
}

impl Write for ByteCounter {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        let added = u64::try_from(buffer.len())
            .map_err(|_| io::Error::other("serialized output length overflow"))?;
        self.bytes = self
            .bytes
            .checked_add(added)
            .ok_or_else(|| io::Error::other("serialized output length overflow"))?;
        Ok(buffer.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn invalid_plan(code: &str) -> LocateOutcome {
    LocateOutcome::Failed {
        failure: LocateFailure::InvalidPlan {
            code: code.to_owned(),
        },
    }
}

fn parse_failure_outcome(code: &str) -> LocateOutcome {
    LocateOutcome::Failed {
        failure: parse_failure(code),
    }
}

const fn limit_failure(limit: ResourceLimit, maximum: u64, observed: u64) -> LocateFailure {
    LocateFailure::LimitExhausted {
        limit,
        maximum,
        observed,
    }
}

fn charge_selector_visit(observed: &mut u64, maximum: u64) -> Result<(), LocateFailure> {
    let next = observed
        .checked_add(1)
        .ok_or_else(|| limit_failure(ResourceLimit::SelectorVisits, maximum, u64::MAX))?;
    if next > maximum {
        return Err(limit_failure(ResourceLimit::SelectorVisits, maximum, next));
    }
    *observed = next;
    Ok(())
}
