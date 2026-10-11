#[cfg(test)]
use std::env;

use super::super::{
    HtmlAttemptFacts, HtmlAttemptFallbackReason, HtmlFallbackReason, HtmlLocateDispatch,
    HtmlPreflightFallbackReason, HtmlStreamingStrategy,
};
use super::config::MAX_STREAMING_ATTRIBUTES;
use super::limits::limits_are_safe;
use super::materialize::materialize;
use super::names::NameKey;
use super::plan::CompiledStreamingPlan;
use super::scanner;
use super::support::{
    Document, LocateOutcome, Plan, ResourceBudget, ResourceLimit, basic, limit_failure, memchr3,
};
use super::tree_text::try_tree_text;

pub(super) struct RelevantAttributes<'source> {
    pub(super) values: [Option<(NameKey, &'source str)>; MAX_STREAMING_ATTRIBUTES],
    pub(super) len: usize,
    pub(super) source_count: u64,
}

impl RelevantAttributes<'_> {
    pub(super) const fn empty() -> Self {
        Self {
            values: [None; MAX_STREAMING_ATTRIBUTES],
            len: 0,
            source_count: 0,
        }
    }
}

pub(in crate::internal::documents::html) fn try_locate(
    document: &Document,
    plan: &Plan,
    budget: ResourceBudget,
) -> HtmlLocateDispatch {
    if document.byte_len() > budget.max_input_bytes() {
        return HtmlLocateDispatch::Terminal {
            outcome: LocateOutcome::Failed {
                failure: limit_failure(
                    ResourceLimit::InputBytes,
                    budget.max_input_bytes(),
                    document.byte_len(),
                ),
            },
        };
    }
    let Ok(compiled) = plan.compiled_tree_plan(budget) else {
        return retained_tree(
            document,
            HtmlFallbackReason::Preflight(HtmlPreflightFallbackReason::PlanUnavailable),
            None,
            None,
        );
    };
    let Some(streaming) = compiled.streaming.as_ref() else {
        return retained_tree(
            document,
            HtmlFallbackReason::Preflight(HtmlPreflightFallbackReason::PlanOutsideCertifiedSubset),
            None,
            None,
        );
    };
    let Some(output) = compiled.outputs.first() else {
        return retained_tree(
            document,
            HtmlFallbackReason::Preflight(HtmlPreflightFallbackReason::PlanUnavailable),
            None,
            None,
        );
    };
    let Ok(source) = basic::from_utf8(document.bytes()) else {
        return retained_tree(
            document,
            HtmlFallbackReason::Preflight(HtmlPreflightFallbackReason::InvalidUtf8),
            None,
            None,
        );
    };
    let source = source.strip_prefix('\u{feff}').unwrap_or(source);
    if memchr3(b'&', b'\0', b'\r', source.as_bytes()).is_some() {
        return retained_tree(
            document,
            HtmlFallbackReason::Preflight(HtmlPreflightFallbackReason::UnsupportedSourceBytes),
            None,
            None,
        );
    }
    match streaming {
        CompiledStreamingPlan::Selector(selector) => {
            let scan = scanner::scan(source, selector, budget);
            #[cfg(test)]
            if matches!(scan, scanner::ScanAttempt::Rejected { .. })
                && env::var_os("YOSOI_ISLAND_TRACE").is_some()
            {
                eprintln!("island reject: scanner proof incomplete");
            }
            let scan = match scan {
                scanner::ScanAttempt::Complete(scan) => scan,
                scanner::ScanAttempt::Rejected {
                    resource_proof_incomplete,
                    parser_offset,
                    candidate_work,
                } => {
                    let reason = if resource_proof_incomplete {
                        HtmlAttemptFallbackReason::ResourceProof
                    } else {
                        HtmlAttemptFallbackReason::Certificate
                    };
                    return retained_tree(
                        document,
                        HtmlFallbackReason::Attempt(reason),
                        parser_offset,
                        Some(candidate_work),
                    );
                }
            };
            let limits_safe = limits_are_safe(&scan, selector.as_ref(), budget);
            #[cfg(test)]
            if !limits_safe && env::var_os("YOSOI_ISLAND_TRACE").is_some() {
                eprintln!(
                    "island reject: resource proof failed; nodes={}, elements={}, depth={}, rightmost={}, attributes={}, scan_work={}",
                    scan.retained_node_upper,
                    scan.element_upper,
                    scan.depth_upper,
                    scan.rightmost_match_count,
                    scan.max_attribute_count,
                    scan.scan_work,
                );
            }
            if !limits_safe {
                let source_bytes = u64::try_from(source.len()).ok();
                return retained_tree(
                    document,
                    HtmlFallbackReason::Attempt(HtmlAttemptFallbackReason::ResourceProof),
                    source_bytes,
                    Some(scan.scan_work),
                );
            }
            match materialize(
                document,
                output.id.as_str(),
                &output.id,
                scan.matches,
                budget,
            ) {
                Some(outcome) => HtmlLocateDispatch::Completed {
                    strategy: HtmlStreamingStrategy::Selector,
                    outcome,
                    attempt: HtmlAttemptFacts {
                        input_bytes_available: document.byte_len(),
                        parser_offset: u64::try_from(source.len()).ok(),
                        candidate_work: Some(scan.scan_work),
                    },
                },
                None => retained_tree(
                    document,
                    HtmlFallbackReason::Attempt(HtmlAttemptFallbackReason::Materialization),
                    u64::try_from(source.len()).ok(),
                    Some(scan.scan_work),
                ),
            }
        }
        CompiledStreamingPlan::TreeText(tree_text) => try_tree_text(
            document,
            output.id.as_str(),
            &output.id,
            source,
            tree_text,
            budget,
        )
        .map_or_else(
            || {
                retained_tree(
                    document,
                    HtmlFallbackReason::Attempt(HtmlAttemptFallbackReason::Certificate),
                    None,
                    None,
                )
            },
            |outcome| HtmlLocateDispatch::Completed {
                strategy: HtmlStreamingStrategy::TreeText,
                outcome,
                attempt: HtmlAttemptFacts {
                    input_bytes_available: document.byte_len(),
                    parser_offset: u64::try_from(source.len()).ok(),
                    candidate_work: None,
                },
            },
        ),
    }
}

const fn retained_tree(
    document: &Document,
    reason: HtmlFallbackReason,
    parser_offset: Option<u64>,
    candidate_work: Option<u64>,
) -> HtmlLocateDispatch {
    HtmlLocateDispatch::RetainedTree {
        reason,
        attempt: HtmlAttemptFacts {
            input_bytes_available: document.byte_len(),
            parser_offset,
            candidate_work,
        },
    }
}
