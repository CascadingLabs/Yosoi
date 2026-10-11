use super::super::config::{EXACT_SELECTOR_METRICS_MIN_BYTES, PARALLEL_MIN_RECORDS};
use super::super::record_certification::certify_hazardous_record;
use super::super::record_metrics::{fast_record_metrics, record_pool};
use super::super::support::{IntoParallelRefIterator, ParallelIterator, mem};
use super::{ImpliedKind, RecordMeasure, RecordMetrics, Scanner};

impl Scanner<'_, '_> {
    pub(super) fn fast_measure_skipped_record(
        &mut self,
        bytes: &[u8],
        outer_implied: ImpliedKind,
    ) -> Option<bool> {
        let outer_depth = self.stack.len();
        match fast_record_metrics(bytes, self.plan, false, outer_implied) {
            RecordMeasure::Metrics(metrics) => {
                self.merge_record_metrics(metrics, outer_depth)?;
                Some(true)
            }
            RecordMeasure::NeedsSequential => {
                self.merge_record_metrics(
                    certify_hazardous_record(bytes, self.plan, outer_implied)?,
                    outer_depth,
                )?;
                Some(true)
            }
            RecordMeasure::Invalid => None,
        }
    }

    fn merge_record_metrics(&mut self, metrics: RecordMetrics, outer_depth: usize) -> Option<()> {
        self.add_nodes(metrics.retained_nodes)?;
        self.element_upper = self.element_upper.checked_add(metrics.elements)?;
        self.scan_work = self.scan_work.checked_add(metrics.work)?;
        self.rightmost_match_count = self
            .rightmost_match_count
            .checked_add(metrics.rightmost_matches)?;
        // Ancestor work is charged per skipped record. A rare deep repair must
        // not multiply every unrelated row's rightmost matches by its depth.
        let absolute_depth_upper = metrics
            .depth
            .checked_add(u64::try_from(outer_depth).ok()?)?
            .checked_add(8)?;
        let ancestor_depth_work = metrics
            .rightmost_matches
            .checked_mul(absolute_depth_upper)?;
        self.rightmost_depth_sum_upper = self
            .rightmost_depth_sum_upper
            .checked_add(ancestor_depth_work)?;
        self.max_attribute_count = self.max_attribute_count.max(metrics.max_attribute_count);
        if self.scan_work > self.budget.max_selector_visits() {
            self.resource_proof_incomplete = true;
            return None;
        }
        let depth = metrics
            .depth
            .checked_add(u64::try_from(outer_depth).ok()?)?;
        self.max_depth = self.max_depth.max(depth);
        Some(())
    }

    pub(super) fn finish_deferred_records(&mut self) -> Option<()> {
        if self.deferred_records.is_empty() {
            return Some(());
        }
        let ranges = mem::take(&mut self.deferred_records);
        let parallel = ranges.len() >= PARALLEL_MIN_RECORDS;
        let source = self.source.as_bytes();
        let plan = self.plan;
        let exact_selector_metrics = source.len() >= EXACT_SELECTOR_METRICS_MIN_BYTES;
        let metrics = if parallel {
            record_pool().map(|pool| {
                pool.install(|| {
                    ranges
                        .par_iter()
                        .map(|(start, end, _outer_depth, outer_implied)| {
                            source
                                .get(*start..*end)
                                .map_or(RecordMeasure::Invalid, |bytes| {
                                    fast_record_metrics(
                                        bytes,
                                        plan,
                                        exact_selector_metrics,
                                        *outer_implied,
                                    )
                                })
                        })
                        .collect::<Vec<_>>()
                })
            })
        } else {
            None
        };
        for (index, (start, end, outer_depth, outer_implied)) in ranges.into_iter().enumerate() {
            let bytes = source.get(start..end)?;
            let measured = metrics
                .as_ref()
                .and_then(|records| records.get(index))
                .copied()
                .unwrap_or_else(|| {
                    fast_record_metrics(bytes, plan, exact_selector_metrics, outer_implied)
                });
            match measured {
                RecordMeasure::Metrics(metrics) => {
                    self.merge_record_metrics(metrics, outer_depth)?;
                }
                RecordMeasure::NeedsSequential => {
                    self.merge_record_metrics(
                        certify_hazardous_record(bytes, plan, outer_implied)?,
                        outer_depth,
                    )?;
                }
                RecordMeasure::Invalid => return None,
            }
        }
        Some(())
    }
}
