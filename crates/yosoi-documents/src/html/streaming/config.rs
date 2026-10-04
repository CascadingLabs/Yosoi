pub(super) const MAX_STREAMING_ATTRIBUTES: usize = 8;
// html5ever 0.39 bounds adoption-agency work to eight outer passes and at
// most three inner clones plus one replacement per pass. Certification also
// caps active formatting entries at eight, so 64 slots per formatting token
// cover adoption and later reconstruction before admitting a streamed result.
pub(super) const REPAIR_NODE_ALLOWANCE: u64 = 64;
pub(super) const MAX_CERTIFIED_FORMATTING_DEPTH: usize = 8;
pub(super) const REPAIR_DEPTH_ALLOWANCE: u64 = 64;
pub(super) const PARALLEL_MIN_BYTES: usize = 65_536;
pub(super) const PARALLEL_MIN_RECORDS: usize = 64;
pub(super) const PARALLEL_MAX_WORKERS: usize = 8;
pub(super) const EXACT_SELECTOR_METRICS_MIN_BYTES: usize = 1_048_576;
