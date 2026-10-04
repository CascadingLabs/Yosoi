pub(super) use std::{
    collections::{HashMap, HashSet},
    mem,
    ops::Range,
    sync::OnceLock,
    thread,
};

pub(super) use memchr::{memchr, memchr3, memmem};
pub(super) use rayon::{ThreadPool, ThreadPoolBuilder, prelude::*};
pub(super) use simdutf8::basic;

pub(super) use crate::region_membership::tree_coordinate_bytes;
pub(super) use crate::{
    Completeness, Document, Finding, LocateOutcome, LocateResult, NativeCoordinate, NodeReference,
    Plan, ProjectedValue, Projection, ResourceBudget, ResourceLimit, TreeCoordinate,
};

pub(super) use super::super::css::{CssCompoundSelector, CssSimpleSelector};
pub(super) use super::super::xpath::{XPathAxis, XPathNameTest, XPathStep};
pub(super) use super::super::{
    Combinator, ElementTree, SelectorElement, SelectorVisitBudget, TextSegment, TreeQuery,
    append_normalized_text, limit_failure, select_tree_text,
};
