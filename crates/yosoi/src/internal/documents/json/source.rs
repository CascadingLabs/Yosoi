use crate::internal::documents::{
    Document, DocumentClass, LocateFailure, LocateOutcome, LocateResult, Plan, Projection,
    QueryAtom, QueryResultShape, ResourceBudget, ResourceLimit,
};

use super::{
    evaluation::{emit_finding, failed, walk_json_path},
    parser::{JSON_PARSER_DEPTH_LIMIT, parse_unique_json, scan_json_depth},
    query::{
        JsonVisitBudget, canonical_pointer, parse_json_path, parse_json_pointer, resolve_pointer,
    },
    types::{JsonParseError, ParsedJsonDocument},
};

impl ParsedJsonDocument {
    /// Evaluates a compiled JSON-only locator plan in deterministic document order.
    #[allow(clippy::manual_let_else, clippy::option_if_let_else)]
    // Query parse failures and result construction use stable public codes.
    pub(in crate::internal::documents) fn locate_with_budget(
        &self,
        plan: &Plan,
        budget: ResourceBudget,
    ) -> LocateOutcome {
        if !plan.requirement().accepts(DocumentClass::SourceJson) {
            return failed(LocateFailure::UnsupportedCombination {
                document: DocumentClass::SourceJson,
            });
        }

        let limits = budget;
        if self.input_bytes > limits.max_input_bytes() {
            return failed(LocateFailure::LimitExhausted {
                limit: ResourceLimit::InputBytes,
                maximum: limits.max_input_bytes(),
                observed: self.input_bytes,
            });
        }
        let maximum_depth = u64::from(limits.max_depth());
        let observed_depth = u64::from(self.maximum_depth);
        if observed_depth > maximum_depth {
            return failed(LocateFailure::LimitExhausted {
                limit: ResourceLimit::Depth,
                maximum: maximum_depth,
                observed: observed_depth,
            });
        }

        if !plan.regions().is_empty() {
            return failed(LocateFailure::InvalidPlan {
                code: "json_regions_are_not_supported".to_owned(),
            });
        }

        let mut findings = Vec::new();
        let mut match_count = 0_u64;
        let mut output_bytes = 0_u64;
        let mut visit_budget = JsonVisitBudget::new(limits.max_selector_visits());

        for output in plan.outputs() {
            match (
                output.query().atom(),
                output.query().result_shape(),
                output.projection(),
            ) {
                (
                    QueryAtom::JsonPointer(expression),
                    QueryResultShape::JsonValues,
                    Projection::JsonValue,
                ) => {
                    let tokens = match parse_json_pointer(expression) {
                        Ok(tokens) => tokens,
                        Err(_) => {
                            return failed(LocateFailure::InvalidPlan {
                                code: "invalid_json_pointer".to_owned(),
                            });
                        }
                    };
                    let value = match resolve_pointer(&self.root, &tokens, &mut visit_budget) {
                        Ok(value) => value,
                        Err(failure) => return failed(failure),
                    };
                    if let Some(value) = value {
                        let pointer = canonical_pointer(&tokens);
                        if let Err(failure) = emit_finding(
                            &self.document_id,
                            output.id(),
                            &pointer,
                            value,
                            limits,
                            &mut findings,
                            &mut match_count,
                            &mut output_bytes,
                        ) {
                            return failed(failure);
                        }
                    }
                }
                (
                    QueryAtom::JsonPath(expression),
                    QueryResultShape::JsonValues,
                    Projection::JsonValue,
                ) => {
                    let selectors = match parse_json_path(expression) {
                        Ok(selectors) => selectors,
                        Err(_) => {
                            return failed(LocateFailure::InvalidPlan {
                                code: "invalid_json_path".to_owned(),
                            });
                        }
                    };
                    let mut path = Vec::new();
                    if let Err(failure) = walk_json_path(
                        &self.root,
                        &selectors,
                        0,
                        &mut path,
                        &self.document_id,
                        output.id(),
                        limits,
                        &mut visit_budget,
                        &mut findings,
                        &mut match_count,
                        &mut output_bytes,
                    ) {
                        return failed(failure);
                    }
                }
                _ => {
                    return failed(LocateFailure::UnsupportedCombination {
                        document: DocumentClass::SourceJson,
                    });
                }
            }
        }

        if findings.is_empty() {
            return LocateOutcome::NoMatch {
                document_id: self.document_id.clone(),
            };
        }

        match LocateResult::try_new(self.document_id.clone(), findings) {
            Ok(result) => LocateOutcome::Matched { result },
            Err(_) => failed(LocateFailure::InvalidPlan {
                code: "invalid_json_evaluation_result".to_owned(),
            }),
        }
    }
}

/// Parses one immutable source-JSON document under explicit byte and depth limits.
pub fn parse_json_document(
    document: &Document,
    limits: ResourceBudget,
) -> Result<ParsedJsonDocument, JsonParseError> {
    if document.class() != DocumentClass::SourceJson {
        return Err(JsonParseError::UnsupportedDocument {
            document: document.class(),
        });
    }

    let maximum_bytes = limits.max_input_bytes();
    if document.byte_len() > maximum_bytes {
        return Err(JsonParseError::InputLimitExceeded {
            maximum: maximum_bytes,
            observed: document.byte_len(),
        });
    }

    // serde_json keeps a defensive recursion limit. Honor both the caller's
    // configured limit and that parser ceiling before entering its recursive parser.
    let maximum_depth = limits.max_depth().min(JSON_PARSER_DEPTH_LIMIT);
    let observed_depth = scan_json_depth(document.bytes(), maximum_depth)?;
    let root = parse_unique_json(document.bytes(), observed_depth)?;

    Ok(ParsedJsonDocument {
        document_id: document.id().clone(),
        root,
        input_bytes: document.byte_len(),
        maximum_depth: observed_depth,
    })
}
