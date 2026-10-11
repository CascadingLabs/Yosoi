use std::collections::BTreeMap;

use regex::Captures;

use crate::internal::documents::{
    ByteRange, Completeness, DecodedTextCoordinate, Document, DocumentClass, Finding,
    LocateFailure, LocateOutcome, LocateResult, NativeCoordinate, Plan, ProjectedValue, Projection,
    QueryAtom, ResourceBudget, TextRange,
};

use super::matching::{EvaluationTotals, invalid_plan, locate_literal, locate_regex, parse_failed};
use super::{CompiledTextRegex, DecodedTextDocument, TextMatch};

impl DecodedTextDocument<'_> {
    /// Locates every text output in plan order and source order.
    pub(in crate::internal::documents) fn locate_with_budget(
        &self,
        plan: &Plan,
        budget: ResourceBudget,
    ) -> Result<LocatedTextEvaluation, LocateFailure> {
        if !plan.requirement().accepts(DocumentClass::SourceText) {
            return Err(LocateFailure::UnsupportedCombination {
                document: self.document.class(),
            });
        }
        if !plan.regions().is_empty() {
            return Err(LocateFailure::InvalidPlan {
                code: "decoded_text_regions_unsupported".to_owned(),
            });
        }

        let mut sink = TextFindingSink::new(self.document, self.text, plan);
        let mut totals = EvaluationTotals::default();
        for (output_index, output) in plan.outputs().iter().enumerate() {
            if let Some(prior_output_index) =
                plan.outputs().iter().take(output_index).position(|prior| {
                    prior.query() == output.query() && prior.projection() == output.projection()
                })
            {
                sink.replay_output(prior_output_index, output_index, budget, &mut totals)?;
                continue;
            }
            match (output.query().atom(), output.projection()) {
                (QueryAtom::TextLiteral(value), Projection::MatchedText) => {
                    locate_literal(
                        self.text,
                        output_index,
                        value,
                        budget,
                        &mut totals,
                        &mut sink,
                    )?;
                }
                (QueryAtom::TextRegex(_), Projection::MatchedText) => {
                    let compiled = plan
                        .compiled_text_regex(output_index)
                        .ok_or_else(|| invalid_plan("compiled_text_regex_missing"))?;
                    locate_regex(
                        self.text,
                        output_index,
                        compiled,
                        &[],
                        budget,
                        &mut totals,
                        &mut sink,
                    )?;
                }
                (QueryAtom::TextRegex(_), Projection::MatchedTextWithCaptures { names }) => {
                    let compiled = plan
                        .compiled_text_regex(output_index)
                        .ok_or_else(|| invalid_plan("compiled_text_regex_missing"))?;
                    locate_regex(
                        self.text,
                        output_index,
                        compiled,
                        names,
                        budget,
                        &mut totals,
                        &mut sink,
                    )?;
                }
                _ => {
                    return Err(LocateFailure::InvalidPlan {
                        code: "decoded_text_query_projection_mismatch".to_owned(),
                    });
                }
            }
        }
        sink.finish()
    }
}

pub(super) struct TextFindingSink<'document, 'plan> {
    document: &'document Document,
    text: &'document str,
    plan: &'plan Plan,
    findings: Vec<Finding>,
}

impl<'document, 'plan> TextFindingSink<'document, 'plan> {
    const fn new(document: &'document Document, text: &'document str, plan: &'plan Plan) -> Self {
        Self {
            document,
            text,
            plan,
            findings: Vec::new(),
        }
    }

    pub(super) fn push_text(&mut self, matched: TextMatch) -> Result<(), LocateFailure> {
        let text = self
            .text
            .get(matched.byte_start..matched.byte_end)
            .ok_or_else(|| parse_failed("invalid_match_range"))?
            .to_owned();
        self.push_value(matched, ProjectedValue::Text(text))
    }

    pub(super) fn push_captures(
        &mut self,
        matched: TextMatch,
        captures: &Captures<'_>,
        compiled: &CompiledTextRegex,
    ) -> Result<(), LocateFailure> {
        let output = self
            .plan
            .outputs()
            .get(matched.output_index)
            .ok_or_else(|| invalid_plan("text_match_output_missing"))?;
        let Projection::MatchedTextWithCaptures { names } = output.projection() else {
            return Err(invalid_plan("decoded_text_projection_mismatch"));
        };
        let groups = compiled.requested_capture_groups();
        if groups.len() != names.len() {
            return Err(invalid_plan("regex_capture_plan_mismatch"));
        }

        let mut projected_captures = BTreeMap::new();
        for (capture_index, group) in groups.iter().copied().enumerate() {
            let Some(capture) = captures.get(group) else {
                continue;
            };
            let name = names
                .get(capture_index)
                .ok_or_else(|| invalid_plan("regex_capture_name_missing"))?;
            projected_captures.insert(name.clone(), capture.as_str().to_owned());
        }
        let text = self
            .text
            .get(matched.byte_start..matched.byte_end)
            .ok_or_else(|| parse_failed("invalid_match_range"))?
            .to_owned();
        self.push_value(
            matched,
            ProjectedValue::TextWithCaptures {
                text,
                captures: projected_captures,
            },
        )
    }

    fn replay_output(
        &mut self,
        source_output_index: usize,
        target_output_index: usize,
        budget: ResourceBudget,
        totals: &mut EvaluationTotals,
    ) -> Result<(), LocateFailure> {
        let source = self
            .plan
            .outputs()
            .get(source_output_index)
            .ok_or_else(|| invalid_plan("text_match_output_missing"))?;
        let target = self
            .plan
            .outputs()
            .get(target_output_index)
            .ok_or_else(|| invalid_plan("text_match_output_missing"))?;
        let prior_finding_count = self.findings.len();
        let mut source_finding_index = 0_usize;
        while source_finding_index < prior_finding_count {
            let Some(source_finding) = self.findings.get(source_finding_index) else {
                return Err(invalid_plan("text_match_output_missing"));
            };
            if source_finding.output_id() != source.id() {
                source_finding_index = source_finding_index
                    .checked_add(1)
                    .ok_or_else(|| parse_failed("finding_order_overflow"))?;
                continue;
            }
            let coordinate = source_finding.coordinate().clone();
            let value = source_finding.value().clone();
            totals.account_replayed_value(&value, budget)?;
            let order = u64::try_from(self.findings.len())
                .map_err(|_| parse_failed("finding_order_overflow"))?;
            let finding = Finding::try_new(
                self.document.id().clone(),
                target.id().clone(),
                order,
                coordinate,
                value,
                Completeness::Complete,
                None,
            )
            .map_err(|_| invalid_plan("invalid_text_finding"))?;
            self.findings.push(finding);
            source_finding_index = source_finding_index
                .checked_add(1)
                .ok_or_else(|| parse_failed("finding_order_overflow"))?;
        }
        Ok(())
    }

    fn push_value(
        &mut self,
        matched: TextMatch,
        value: ProjectedValue,
    ) -> Result<(), LocateFailure> {
        let output = self
            .plan
            .outputs()
            .get(matched.output_index)
            .ok_or_else(|| invalid_plan("text_match_output_missing"))?;
        let byte_start =
            u64::try_from(matched.byte_start).map_err(|_| parse_failed("coordinate_overflow"))?;
        let byte_end =
            u64::try_from(matched.byte_end).map_err(|_| parse_failed("coordinate_overflow"))?;
        let byte_range = ByteRange::try_new(byte_start, byte_end)
            .map_err(|_| parse_failed("invalid_byte_range"))?;
        let scalar_range = TextRange::try_new(matched.scalar_start, matched.scalar_end)
            .map_err(|_| parse_failed("invalid_scalar_range"))?;
        let coordinate =
            NativeCoordinate::DecodedText(DecodedTextCoordinate::new(byte_range, scalar_range));
        let order = u64::try_from(self.findings.len())
            .map_err(|_| parse_failed("finding_order_overflow"))?;
        let finding = Finding::try_new(
            self.document.id().clone(),
            output.id().clone(),
            order,
            coordinate,
            value,
            Completeness::Complete,
            None,
        )
        .map_err(|_| invalid_plan("invalid_text_finding"))?;
        self.findings.push(finding);
        Ok(())
    }

    fn finish(self) -> Result<LocatedTextEvaluation, LocateFailure> {
        let outcome = if self.findings.is_empty() {
            LocateOutcome::NoMatch {
                document_id: self.document.id().clone(),
            }
        } else {
            let result = LocateResult::try_new(self.document.id().clone(), self.findings)
                .map_err(|_| invalid_plan("invalid_text_result_order"))?;
            LocateOutcome::Matched { result }
        };
        Ok(LocatedTextEvaluation { outcome })
    }
}

/// A completed decoded-text evaluation awaiting the common materialization boundary.
#[derive(Clone, Debug)]
pub struct LocatedTextEvaluation {
    outcome: LocateOutcome,
}

impl LocatedTextEvaluation {
    pub fn materialize(self) -> LocateOutcome {
        self.outcome
    }
}
