//! Task-independent observation surfaces and cursor sessions.
//!
//! Prepare immutable evidence once, then retrieve bounded overview, region,
//! search, and inspection responses. References identify one exact capture;
//! they do not grant browser control or imply cross-capture identity. The Rust
//! session coordinates readers, scoped watches, and one hot owner.
//! External adapters still own capture, final live eligibility, and effects.

#[cfg(any(feature = "browser", feature = "surface-video"))]
pub mod archive;
#[cfg(any(feature = "browser", feature = "surface-video"))]
mod connection;
mod images;
pub mod model;
mod outcome;
mod policy;
mod prepare;
#[cfg(any(feature = "browser", feature = "surface-video"))]
pub use connection::SurfaceConnection;
pub mod browser;
mod session;
#[cfg(feature = "surface-video")]
pub mod video;

#[cfg(any(feature = "browser", feature = "surface-images"))]
pub use images::ImageCrop;
pub use images::PixelRect;
pub use outcome::{ArchivedSource, Outcome, OutcomeRef, SourceInterpretation};
pub use policy::{ArchiveLimits, ArchivePolicy, ExecutionError, SurfacePolicy};
pub use session::*;

use crate::documents::{Document, DocumentId, DocumentProfile};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fmt,
    sync::Arc,
};
use thiserror::Error;

/// Checked failures from surface preparation, reading or session control.
#[derive(Debug, Error)]
pub enum SurfaceError {
    /// The input or requested operation is invalid.
    #[error("invalid surface input: {0}")]
    Invalid(String),
    /// Parsing or encoding failed without a usable result.
    #[error("surface interpretation failed: {0}")]
    Parse(String),
    /// A declared resource bound was exceeded.
    #[error("surface limit exceeded: {0}")]
    Limit(&'static str),
    /// The reference addresses another immutable capture.
    #[error("reference belongs to a different capture")]
    WrongCapture,
    /// The requested node, cursor, watch, or retained capture is unavailable.
    #[error("unknown or evicted index object")]
    Unknown,
    /// The response cannot fit one useful item and its metadata.
    #[error("response budget cannot fit a useful result")]
    BudgetTooSmall,
    /// An action requires an attached live session.
    #[error("cursor session is detached")]
    Detached,
    /// Another cursor owns the single hot capability.
    #[error("another cursor owns hot authority")]
    HotOwned,
    /// This cursor does not own hot action authority.
    #[error("cursor is a reader, not the hot owner")]
    ReaderOnly,
    /// A current action prevents handoff or another action.
    #[error("an action lease is already in flight")]
    ActionInFlight,
    /// The selected evidence or issued permit is stale.
    #[error("focused evidence or action lease is stale")]
    Stale,
    /// Observation coverage cannot support the requested claim.
    #[error("observation coverage is incomplete or unknown")]
    Uncertain,
    /// A shared session lock was poisoned; authority is not assumed.
    #[error("session state is unavailable after lock poisoning")]
    Poisoned,
}

/// Resource bounds for preparation, independent of any model or task.
#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Limits {
    /// Maximum retained input bytes.
    pub input_bytes: usize,
    /// Maximum indexed nodes, including text/scalar nodes.
    pub nodes: usize,
    /// Maximum source tree depth.
    pub depth: usize,
    /// Maximum depth expanded automatically in an overview.
    pub overview_depth: usize,
}
impl Default for Limits {
    fn default() -> Self {
        Self {
            input_bytes: 8 * 1024 * 1024,
            nodes: 200_000,
            depth: 96,
            overview_depth: 6,
        }
    }
}

/// A per-response bound on serialized JSON bytes and returned entries.
#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Budget {
    /// Whole serialized response limit, including references and continuation.
    pub bytes: usize,
    /// Maximum entries in one response; clamped to 100.
    pub items: usize,
}
impl Default for Budget {
    fn default() -> Self {
        Self {
            bytes: 4096,
            items: 20,
        }
    }
}

/// Address of one node within one exact immutable interpretation.
#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq, Ord, PartialOrd)]
pub struct Reference {
    /// Content, document identity, profile, and interpreter-bound capture digest.
    pub capture: String,
    /// Opaque node ordinal within that capture; never a durable entity ID.
    pub node: usize,
}

/// Representation-native evidence address, not an executable browser selector.
#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
pub struct Coordinate {
    /// Address grammar, such as `html_element`, `json_pointer`, or `image_rect`.
    pub kind: String,
    /// Grammar-specific value; scoped to the reference's capture.
    pub value: String,
}

/// Origin of a reference projected into a named combined observation view.
#[derive(Clone, Debug, Serialize)]
pub struct SourceReference {
    /// Name of the constituent view, such as `document` or `screenshot`.
    pub view: String,
    /// Exact original source reference, retaining its own capture provenance.
    pub reference: Reference,
}

/// Source coverage, kept separate from omission due to response budgets.
#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
pub struct Coverage {
    /// Whether the supplied evidence declares complete coverage of its scope.
    pub complete: bool,
    /// Structural reason for partial/unknown coverage, if any.
    pub reason: Option<String>,
}

/// A compact routing entry whose original evidence remains inspectable.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Entry {
    /// Exact recoverable evidence reference.
    pub reference: Reference,
    /// Representation-neutral node kind.
    pub kind: String,
    /// Structural name, role, or field name, clipped to 96 characters for routing.
    pub label: String,
    /// Bounded routing preview, not a model-generated summary.
    pub preview: String,
    /// Number of addressable direct members when this is a repeat region.
    pub members: Option<usize>,
    /// Exact first member of a collapsed region, for one-hop exemplar inspection.
    pub exemplar: Option<Reference>,
    /// Bounded exemplar structure, not a complete inferred schema.
    pub shape: Option<String>,
    /// Constituent view name when this entry belongs to a combined observation.
    pub view: Option<String>,
}

/// A continuation bound to capture, operation, scope, and search expression.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Continuation {
    capture: String,
    operation: String,
    scope: usize,
    query: String,
    offset: usize,
}
impl Continuation {
    /// Returns the next member, entry, or UTF-8 content-byte offset.
    pub const fn offset(&self) -> usize {
        self.offset
    }
}

/// A bounded overview, member page, or literal-search page.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Page {
    /// Exact interpretation being read.
    pub capture: String,
    /// Operation that produced this page.
    pub operation: String,
    /// Eligible entries in the full addressed population.
    pub total: usize,
    /// Starting offset within that population.
    pub offset: usize,
    /// Entries included in this response.
    pub entries: Vec<Entry>,
    /// Number of population entries absent from this particular response.
    pub omitted: usize,
    /// Next window of the same operation, if more remain after this page.
    pub next: Option<Continuation>,
    /// Completeness of the source, independent of paging.
    pub coverage: Coverage,
}

/// Bounded source-backed detail; text chunks need not be valid whole documents.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Inspection {
    /// Exact selected evidence.
    pub reference: Reference,
    /// Interpretation and normalization of the returned text.
    pub media_type: String,
    /// Total UTF-8 bytes in the complete selected serialization.
    pub total_bytes: usize,
    /// UTF-8 byte offset of this chunk.
    pub offset: usize,
    /// This response's text content.
    pub content: String,
    /// Continuation to the next UTF-8-aligned content chunk.
    pub next: Option<Continuation>,
    /// Coverage of the original evidence.
    pub coverage: Coverage,
}

#[derive(Clone, Debug)]
enum Payload {
    Tree,
    Range(usize, usize),
    Json(String),
    Literal(String),
    Bundle,
    External {
        view: usize,
        node: usize,
    },
    #[cfg(any(feature = "browser", feature = "surface-images"))]
    Image(PixelRect),
}

#[derive(Clone, Debug)]
struct Node {
    kind: String,
    name: String,
    text: String,
    attrs: BTreeMap<String, String>,
    children: Vec<usize>,
    parent: Option<usize>,
    coordinate: Coordinate,
    payload: Payload,
}

#[derive(Debug)]
struct Data {
    original: Option<Original>,
    identity: String,
    source: String,
    input_bytes: usize,
    representation: String,
    nodes: Vec<Node>,
    coverage: Coverage,
    overview: Vec<usize>,
    repeated: BTreeMap<usize, Vec<usize>>,
    json: Option<Value>,
    views: Vec<(String, Surface)>,
    #[cfg(any(feature = "browser", feature = "surface-images"))]
    image: Option<Arc<images::ImageData>>,
}

#[derive(Debug)]
enum Original {
    Document {
        id: DocumentId,
        profile: DocumentProfile,
    },
    #[cfg(any(feature = "browser", feature = "surface-images"))]
    Image { bytes: Vec<u8>, tile_side: u32 },
}

/// Reusable immutable index, safe to share between concurrent Rust readers.
#[derive(Clone)]
pub struct Surface {
    data: Arc<Data>,
}
impl fmt::Debug for Surface {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Surface")
            .field("capture", &self.identity())
            .field("representation", &self.representation())
            .field("source_bytes", &self.source_bytes())
            .field("nodes", &self.node_count())
            .field("coverage", self.coverage())
            .finish_non_exhaustive()
    }
}

impl Surface {
    /// Combines named document/image views into one address space without claiming atomic capture.
    /// Each original source keeps its identity. Nested bundles are intentionally unsupported.
    pub fn combine(
        scope: &str,
        views: Vec<(String, Self)>,
        limits: Limits,
    ) -> Result<Self, SurfaceError> {
        if scope.trim().is_empty() || scope.len() > 256 || views.is_empty() || views.len() > 16 {
            return Err(SurfaceError::Invalid(
                "bundle requires a scope and 1..=16 views".into(),
            ));
        }
        let mut names = BTreeSet::new();
        let mut input_bytes = 0usize;
        let mut nodes = vec![Node {
            kind: "observation".into(),
            name: "observation".into(),
            text: scope.into(),
            attrs: BTreeMap::new(),
            children: Vec::new(),
            parent: None,
            coordinate: Coordinate {
                kind: "observation_manifest".into(),
                value: scope.into(),
            },
            payload: Payload::Bundle,
        }];
        for (view, (name, index)) in views.iter().enumerate() {
            if name.is_empty()
                || name.len() > 64
                || !name
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || b"_-".contains(&byte))
                || !names.insert(name.clone())
            {
                return Err(SurfaceError::Invalid(
                    "view names must be unique 1..=64 ASCII letters/digits/_/-".into(),
                ));
            }
            if !index.data.views.is_empty() {
                return Err(SurfaceError::Invalid(
                    "nested observation bundles are not supported".into(),
                ));
            }
            input_bytes = input_bytes
                .checked_add(index.source_bytes())
                .ok_or(SurfaceError::Limit("bundle input bytes"))?;
            if input_bytes > limits.input_bytes
                || nodes
                    .len()
                    .checked_add(index.node_count())
                    .is_none_or(|count| count > limits.nodes)
            {
                return Err(SurfaceError::Limit("bundle evidence"));
            }
            let base = nodes.len();
            nodes
                .get_mut(0)
                .ok_or(SurfaceError::Unknown)?
                .children
                .push(base);
            let mut depths = Vec::<usize>::new();
            for (id, source) in index.data.nodes.iter().enumerate() {
                let depth = if let Some(parent) = source.parent {
                    depths
                        .get(parent)
                        .ok_or(SurfaceError::Unknown)?
                        .checked_add(1)
                        .ok_or(SurfaceError::Limit("bundle depth"))?
                } else {
                    1
                };
                if depth > limits.depth {
                    return Err(SurfaceError::Limit("bundle depth"));
                }
                depths.push(depth);
                let mut proxy = source.clone();
                proxy.parent = if id == 0 {
                    Some(0)
                } else {
                    source.parent.map(|parent| base.saturating_add(parent))
                };
                proxy.children = source
                    .children
                    .iter()
                    .map(|id| base.saturating_add(*id))
                    .collect();
                proxy.coordinate.kind = format!("view/{name}/{}", proxy.coordinate.kind);
                proxy.payload = Payload::External { view, node: id };
                if id == 0 {
                    proxy.kind = "view".into();
                    proxy.name.clone_from(name);
                }
                nodes.push(proxy);
            }
        }
        let manifest = serde_json::json!({"interpreter":"yosoi-observation-bundle-v2","scope":scope,"views":views.iter().map(|(name,index)|serde_json::json!({"name":name,"capture":index.identity()})).collect::<Vec<_>>()});
        let identity = format!("observation-v2:{:x}", Sha256::digest(encoded(&manifest)?));
        let complete = views.iter().all(|(_, index)| index.coverage().complete);
        let mut data = Data {
            original: None,
            identity,
            source: String::new(),
            input_bytes,
            representation: "application/vnd.yosoi.observation-bundle; atomic=false".into(),
            nodes,
            coverage: Coverage {
                complete,
                reason: (!complete)
                    .then(|| "one or more constituent views have incomplete coverage".into()),
            },
            overview: Vec::new(),
            repeated: BTreeMap::new(),
            json: None,
            views,
            #[cfg(any(feature = "browser", feature = "surface-images"))]
            image: None,
        };
        prepare::reduce(&mut data, limits.overview_depth)?;
        Ok(Self {
            data: Arc::new(data),
        })
    }
    /// Prepares any of Yosoi's six supported document classes with default limits.
    /// This performs no network, model, browser, or task-specific operation.
    pub fn new(document: &Document) -> Result<Self, SurfaceError> {
        Self::with_limits(document, Limits::default())
    }
    /// Prepares evidence with explicit resource limits and interpreter-bound identity.
    pub fn with_limits(document: &Document, limits: Limits) -> Result<Self, SurfaceError> {
        prepare::document(document, limits)
    }
    /// Returns the exact immutable capture identity.
    pub fn identity(&self) -> &str {
        &self.data.identity
    }
    /// Returns the input representation, not a claim about live visibility.
    pub fn representation(&self) -> &str {
        &self.data.representation
    }
    /// Returns original retained input bytes.
    pub fn source_bytes(&self) -> usize {
        self.data.input_bytes
    }
    /// Returns indexed nodes, including text/scalar nodes.
    pub fn node_count(&self) -> usize {
        self.data.nodes.len()
    }
    /// Returns declared source coverage.
    pub fn coverage(&self) -> &Coverage {
        &self.data.coverage
    }
    /// Returns the document/root evidence reference.
    pub fn root(&self) -> Reference {
        self.reference(0)
    }
    fn reference(&self, node: usize) -> Reference {
        Reference {
            capture: self.data.identity.clone(),
            node,
        }
    }
    fn node(&self, reference: &Reference) -> Result<&Node, SurfaceError> {
        if reference.capture != self.identity() {
            return Err(SurfaceError::WrongCapture);
        }
        self.data
            .nodes
            .get(reference.node)
            .ok_or(SurfaceError::Unknown)
    }
    /// Validates exact capture membership and node existence, not live eligibility.
    pub fn validate(&self, reference: &Reference) -> Result<(), SurfaceError> {
        self.node(reference).map(|_| ())
    }
    /// Returns native evidence coordinates without granting effect authority.
    pub fn coordinate(&self, reference: &Reference) -> Result<Coordinate, SurfaceError> {
        Ok(self.node(reference)?.coordinate.clone())
    }
    /// Resolves a combined-view projection to its exact original evidence reference.
    /// `None` means this reference is not a projected source node.
    pub fn source_reference(
        &self,
        reference: &Reference,
    ) -> Result<Option<SourceReference>, SurfaceError> {
        let node = self.node(reference)?;
        if let Payload::External { view, node } = node.payload {
            let (name, index) = self.data.views.get(view).ok_or(SurfaceError::Unknown)?;
            Ok(Some(SourceReference {
                view: name.clone(),
                reference: index.reference(node),
            }))
        } else {
            Ok(None)
        }
    }
    /// Borrows a constituent prepared view by cheaply cloning its immutable handle.
    pub fn view(&self, name: &str) -> Option<Self> {
        self.data
            .views
            .iter()
            .find(|(label, _)| label == name)
            .map(|(_, index)| index.clone())
    }
    /// Projects an exact constituent reference into this combined observation.
    /// This does not rebind a reference from another capture or infer entity identity.
    pub fn project(&self, name: &str, reference: &Reference) -> Result<Reference, SurfaceError> {
        let (position, (_, source)) = self
            .data
            .views
            .iter()
            .enumerate()
            .find(|(_, (label, _))| label == name)
            .ok_or(SurfaceError::Unknown)?;
        source.validate(reference)?;
        let base = self
            .data
            .nodes
            .first()
            .and_then(|root| root.children.get(position))
            .ok_or(SurfaceError::Unknown)?;
        Ok(self.reference(
            base.checked_add(reference.node)
                .ok_or(SurfaceError::Limit("view projection"))?,
        ))
    }
    /// Returns the selected node's parent, or `None` at the root.
    pub fn parent(&self, reference: &Reference) -> Result<Option<Reference>, SurfaceError> {
        Ok(self.node(reference)?.parent.map(|n| self.reference(n)))
    }
    fn entry(&self, id: usize) -> Result<Entry, SurfaceError> {
        let node = self.data.nodes.get(id).ok_or(SurfaceError::Unknown)?;
        let mut preview = String::new();
        let mut pending = vec![id];
        while let Some(next) = pending.pop() {
            let child = self.data.nodes.get(next).ok_or(SurfaceError::Unknown)?;
            if next != id
                && (matches!(child.name.as_str(), "script" | "style") || child.kind == "comment")
            {
                continue;
            }
            if !child.text.is_empty() {
                preview.extend(
                    child
                        .text
                        .chars()
                        .take(160usize.saturating_sub(preview.chars().count())),
                );
                preview.push(' ');
            }
            if preview.chars().count() >= 160 {
                break;
            }
            if child.kind == "accessibility" && !child.text.is_empty() {
                continue;
            }
            pending.extend(child.children.iter().rev().copied());
        }
        let exemplar = self
            .data
            .repeated
            .get(&id)
            .and_then(|members| members.first())
            .copied();
        let shape = exemplar
            .and_then(|id| self.data.nodes.get(id))
            .map(|member| {
                let children = member
                    .children
                    .iter()
                    .filter_map(|id| self.data.nodes.get(*id))
                    .filter(|node| node.kind != "text" || !node.text.trim().is_empty())
                    .take(8)
                    .map(|node| node.name.as_str())
                    .collect::<Vec<_>>()
                    .join(", ");
                format!("{} → [{children}]", member.name)
                    .chars()
                    .take(160)
                    .collect()
            });
        Ok(Entry {
            reference: self.reference(id),
            kind: node.kind.clone(),
            label: node.name.chars().take(96).collect(),
            preview: preview
                .split_whitespace()
                .collect::<Vec<_>>()
                .join(" ")
                .chars()
                .take(160)
                .collect(),
            members: self.data.repeated.get(&id).map(Vec::len),
            exemplar: exemplar.map(|id| self.reference(id)),
            shape,
            view: if let Payload::External { view, .. } = node.payload {
                self.data.views.get(view).map(|(name, _)| name.clone())
            } else {
                None
            },
        })
    }
    fn offset(
        &self,
        token: Option<&Continuation>,
        operation: &str,
        scope: usize,
        query: &str,
    ) -> Result<usize, SurfaceError> {
        match token {
            None => Ok(0),
            Some(token)
                if token.capture == self.identity()
                    && token.operation == operation
                    && token.scope == scope
                    && token.query == query =>
            {
                Ok(token.offset)
            }
            Some(_) => Err(SurfaceError::Invalid(
                "continuation belongs to another operation, capture, scope, or query".into(),
            )),
        }
    }
    fn page(
        &self,
        ids: &[usize],
        operation: &str,
        scope: usize,
        query: &str,
        token: Option<&Continuation>,
        budget: Budget,
    ) -> Result<Page, SurfaceError> {
        if budget.items == 0 || budget.bytes == 0 {
            return Err(SurfaceError::BudgetTooSmall);
        }
        let offset = self.offset(token, operation, scope, query)?;
        if offset > ids.len() {
            return Err(SurfaceError::Invalid(
                "continuation offset outside population".into(),
            ));
        }
        let mut page = Page {
            capture: self.identity().into(),
            operation: operation.into(),
            total: ids.len(),
            offset,
            entries: Vec::new(),
            omitted: ids.len(),
            next: None,
            coverage: self.coverage().clone(),
        };
        for id in ids.iter().skip(offset).take(budget.items.clamp(1, 100)) {
            page.entries.push(self.entry(*id)?);
            let next = offset
                .checked_add(page.entries.len())
                .ok_or(SurfaceError::Limit("page arithmetic"))?;
            page.next = (next < ids.len()).then(|| Continuation {
                capture: self.identity().into(),
                operation: operation.into(),
                scope,
                query: query.into(),
                offset: next,
            });
            page.omitted = ids.len().saturating_sub(page.entries.len());
            if encoded(&page)?.len() > budget.bytes {
                page.entries.pop();
                break;
            }
        }
        if page.entries.is_empty() && offset < ids.len() {
            return Err(SurfaceError::BudgetTooSmall);
        }
        let next = offset
            .checked_add(page.entries.len())
            .ok_or(SurfaceError::Limit("page arithmetic"))?;
        page.next = (next < ids.len()).then(|| Continuation {
            capture: self.identity().into(),
            operation: operation.into(),
            scope,
            query: query.into(),
            offset: next,
        });
        page.omitted = ids.len().saturating_sub(page.entries.len());
        if encoded(&page)?.len() > budget.bytes {
            return Err(SurfaceError::BudgetTooSmall);
        }
        Ok(page)
    }
    /// Returns a structural overview, collapsing homogeneous repeated siblings.
    /// Omitted entries remain reachable through continuation or root expansion.
    pub fn overview(
        &self,
        token: Option<&Continuation>,
        budget: Budget,
    ) -> Result<Page, SurfaceError> {
        self.page(&self.data.overview, "overview", 0, "", token, budget)
    }
    /// Returns direct members of one region, independently of the overview budget.
    pub fn expand(
        &self,
        reference: &Reference,
        token: Option<&Continuation>,
        budget: Budget,
    ) -> Result<Page, SurfaceError> {
        let children = &self.node(reference)?.children;
        self.page(
            self.data
                .repeated
                .get(&reference.node)
                .map_or(children, |members| members),
            "expand",
            reference.node,
            "",
            token,
            budget,
        )
    }
    /// Finds literal text in leaf/scalar evidence and attributes without a model.
    /// Search is task-directed; index construction is not. Results retain source order.
    pub fn find(
        &self,
        query: &str,
        token: Option<&Continuation>,
        budget: Budget,
    ) -> Result<Page, SurfaceError> {
        if query.trim().is_empty() || query.len() > 256 {
            return Err(SurfaceError::Invalid(
                "search requires 1..=256 UTF-8 bytes".into(),
            ));
        }
        let lower = query.to_lowercase();
        let ids: Vec<_> = self
            .data
            .nodes
            .iter()
            .enumerate()
            .filter(|(_, node)| {
                node.text.to_lowercase().contains(&lower)
                    || node
                        .attrs
                        .values()
                        .any(|value| value.to_lowercase().contains(&lower))
            })
            .map(|(id, _)| id)
            .collect();
        self.page(&ids, "find", 0, query, token, budget)
    }
    /// Reads exact XML/text ranges or normalized HTML/JSON/snapshot evidence.
    /// Continuation chunks are UTF-8 aligned; concatenation reconstructs the serialization.
    pub fn inspect(
        &self,
        reference: &Reference,
        token: Option<&Continuation>,
        budget: Budget,
    ) -> Result<Inspection, SurfaceError> {
        self.node(reference)?;
        let content = self.detail(reference.node)?;
        let offset = self.offset(token, "inspect", reference.node, "")?;
        let remaining = content
            .get(offset..)
            .ok_or_else(|| SurfaceError::Invalid("invalid UTF-8 content offset".into()))?;
        let mut part: String = remaining.chars().take(budget.bytes).collect();
        loop {
            if part.is_empty() && !remaining.is_empty() {
                return Err(SurfaceError::BudgetTooSmall);
            }
            let next = offset
                .checked_add(part.len())
                .ok_or(SurfaceError::Limit("inspection arithmetic"))?;
            let inspection = Inspection {
                reference: reference.clone(),
                media_type: self.data.representation.clone(),
                total_bytes: content.len(),
                offset,
                content: part.clone(),
                next: (next < content.len()).then(|| Continuation {
                    capture: self.identity().into(),
                    operation: "inspect".into(),
                    scope: reference.node,
                    query: String::new(),
                    offset: next,
                }),
                coverage: self.coverage().clone(),
            };
            if encoded(&inspection)?.len() <= budget.bytes {
                return Ok(inspection);
            }
            if part.is_empty() {
                return Err(SurfaceError::BudgetTooSmall);
            }
            for _ in 0..32 {
                part.pop();
            }
        }
    }
    fn detail(&self, id: usize) -> Result<String, SurfaceError> {
        let node = self.data.nodes.get(id).ok_or(SurfaceError::Unknown)?;
        match &node.payload {
            Payload::Bundle=>serde_json::to_string(&serde_json::json!({"scope":node.text,"atomic":false,"views":self.data.views.iter().map(|(name,index)|serde_json::json!({"name":name,"capture":index.identity(),"representation":index.representation(),"coverage":index.coverage()})).collect::<Vec<_>>()})).map_err(|e|SurfaceError::Parse(e.to_string())),
            Payload::External{view,node}=>self.data.views.get(*view).ok_or(SurfaceError::Unknown)?.1.detail(*node),
            Payload::Range(start, end) => self
                .data
                .source
                .get(*start..*end)
                .map(str::to_string)
                .ok_or(SurfaceError::Unknown),
            Payload::Literal(text) => Ok(text.clone()),
            Payload::Json(pointer) => self
                .data
                .json
                .as_ref()
                .and_then(|value| value.pointer(pointer))
                .ok_or(SurfaceError::Unknown)
                .and_then(|value| {
                    serde_json::to_string(value).map_err(|e| SurfaceError::Parse(e.to_string()))
                }),
            #[cfg(any(feature = "browser", feature = "surface-images"))]
            Payload::Image(rect) => {
                serde_json::to_string(rect).map_err(|e| SurfaceError::Parse(e.to_string()))
            }
            Payload::Tree => prepare::serialize(&self.data.nodes, id),
        }
    }
    fn comparison_digest(&self, id: usize) -> Result<Vec<u8>, SurfaceError> {
        let node = self.data.nodes.get(id).ok_or(SurfaceError::Unknown)?;
        if let Payload::External { view, node } = node.payload {
            return self
                .data
                .views
                .get(view)
                .ok_or(SurfaceError::Unknown)?
                .1
                .comparison_digest(node);
        }
        if matches!(node.payload, Payload::Bundle) {
            let mut digest = Sha256::new();
            for (name, index) in &self.data.views {
                digest.update(name.as_bytes());
                digest.update(index.comparison_digest(0)?);
            }
            return Ok(digest.finalize().to_vec());
        }
        #[cfg(any(feature = "browser", feature = "surface-images"))]
        if let Payload::Image(rect) = node.payload {
            return images::region_digest(
                self.data.image.as_deref().ok_or(SurfaceError::Unknown)?,
                rect,
            );
        }
        let mut digest = Sha256::new();
        if matches!(node.payload, Payload::Literal(_)) {
            // Native snapshot nodes encode child identities, not descendant values.
            let mut pending = vec![id];
            while let Some(next) = pending.pop() {
                let node = self.data.nodes.get(next).ok_or(SurfaceError::Unknown)?;
                let content = self.detail(next)?;
                digest.update(content.len().to_le_bytes());
                digest.update(content.as_bytes());
                pending.extend(node.children.iter().rev().copied());
            }
        } else {
            digest.update(self.detail(id)?.as_bytes());
        }
        Ok(digest.finalize().to_vec())
    }
}

fn encoded<T: Serialize>(value: &T) -> Result<Vec<u8>, SurfaceError> {
    serde_json::to_vec(value).map_err(|e| SurfaceError::Parse(e.to_string()))
}
