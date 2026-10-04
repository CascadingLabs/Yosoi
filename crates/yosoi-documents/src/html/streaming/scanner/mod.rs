use super::names::NameKey;
use super::plan::CompiledSelectorPlan;
use super::support::{HashMap, HashSet, ResourceBudget, TreeCoordinate};

pub(super) struct OpenElement {
    id: u64,
    name: NameKey,
    ordinal: u32,
    child_count: u32,
    leftmost_root: u64,
    match_id: usize,
    flags: u8,
    pub(super) implied: ImpliedKind,
    pub(super) closes_paragraph: bool,
}

const INSIDE_CANDIDATE: u8 = 1;
const CANDIDATE_TABLE: u8 = 2;
const CANDIDATE_FOREIGN: u8 = 4;
const FOREIGN_CONTEXT: u8 = 8;

impl OpenElement {
    const fn has_flag(&self, flag: u8) -> bool {
        self.flags & flag != 0
    }
}

#[derive(Clone, Copy, Eq, PartialEq)]
pub(super) enum ImpliedKind {
    Other,
    Paragraph,
    ListItem,
    DefinitionTerm,
    DefinitionDescription,
    Heading,
    Button,
    Form,
}

#[derive(Clone, Copy)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "cached tag facts avoid repeated classification in the scanner hot loop"
)]
pub(super) struct TagFacts {
    pub(super) leftmost: bool,
    pub(super) rightmost: bool,
    pub(super) void: bool,
    pub(super) unsupported: bool,
    pub(super) formatting: bool,
    pub(super) table: bool,
    pub(super) foreign: bool,
    pub(super) implied: ImpliedKind,
    pub(super) closes_paragraph: bool,
}

pub(super) struct StreamMatch {
    pub(super) coordinate: TreeCoordinate,
    pub(super) value: StreamValue,
}

pub(super) enum StreamValue {
    Text {
        value: String,
        previous_was_space: bool,
    },
    Attribute {
        name: String,
        value: String,
    },
    Node,
}

pub(super) struct ScanResult {
    pub(super) matches: Vec<StreamMatch>,
    pub(super) retained_node_upper: u64,
    pub(super) element_upper: u64,
    pub(super) depth_upper: u64,
    pub(super) rightmost_match_count: u64,
    pub(super) rightmost_depth_sum_upper: u64,
    pub(super) max_attribute_count: u64,
    pub(super) scan_work: u64,
}

pub(super) enum ScanAttempt {
    Complete(ScanResult),
    Rejected {
        resource_proof_incomplete: bool,
        parser_offset: Option<u64>,
        candidate_work: u64,
    },
}

#[derive(Clone, Copy)]
pub(super) struct RecordMetrics {
    pub(super) retained_nodes: u64,
    pub(super) elements: u64,
    pub(super) depth: u64,
    pub(super) work: u64,
    pub(super) rightmost_matches: u64,
    pub(super) max_attribute_count: u64,
}

#[derive(Clone, Copy)]
pub(super) enum RecordMeasure {
    Metrics(RecordMetrics),
    NeedsSequential,
    Invalid,
}

struct Scanner<'source, 'plan> {
    source: &'source str,
    plan: &'plan CompiledSelectorPlan,
    budget: ResourceBudget,
    stack: Vec<OpenElement>,
    matches: Vec<StreamMatch>,
    active_match: Option<usize>,
    next_id: u64,
    root_count: u32,
    html_children: Vec<NameKey>,
    candidate_parent: Option<u64>,
    grid_parent: Option<u64>,
    candidate_roots: HashSet<u64>,
    hazard_roots: HashSet<u64>,
    first_table_by_root: HashMap<u64, usize>,
    retained_node_upper: u64,
    element_upper: u64,
    scan_work: u64,
    max_depth: u64,
    rightmost_match_count: u64,
    rightmost_depth_sum_upper: u64,
    max_attribute_count: u64,
    projected_value_bytes: u64,
    parser_offset: Option<u64>,
    resource_proof_incomplete: bool,
    table_depth: u32,
    foreign_depth: u32,
    deferred_records: Vec<(usize, usize, usize, ImpliedKind)>,
}

mod elements;
mod records;
mod run;

pub(super) fn scan(
    source: &str,
    plan: &CompiledSelectorPlan,
    budget: ResourceBudget,
) -> ScanAttempt {
    run::scan(source, plan, budget)
}
