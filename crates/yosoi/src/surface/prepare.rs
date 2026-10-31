use super::{Coordinate, Coverage, Data, Limits, Node, Payload, Surface, SurfaceError};
use crate::documents::{Document, DocumentClass};
use html5ever::{ParseOpts, parse_document, tendril::TendrilSink};
use markup5ever_rcdom::{NodeData, RcDom};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, str::from_utf8, sync::Arc};

struct Builder {
    nodes: Vec<Node>,
    limits: Limits,
}
impl Builder {
    fn push(&mut self, node: Node, depth: usize) -> Result<usize, SurfaceError> {
        if depth > self.limits.depth {
            return Err(SurfaceError::Limit("tree depth"));
        }
        if self.nodes.len() >= self.limits.nodes {
            return Err(SurfaceError::Limit("node count"));
        }
        let id = self.nodes.len();
        if let Some(parent) = node.parent {
            self.nodes
                .get_mut(parent)
                .ok_or(SurfaceError::Unknown)?
                .children
                .push(id);
        }
        self.nodes.push(node);
        Ok(id)
    }
}
fn node(
    kind: &str,
    name: String,
    text: String,
    parent: Option<usize>,
    coordinate: Coordinate,
    payload: Payload,
) -> Node {
    Node {
        kind: kind.into(),
        name,
        text,
        attrs: BTreeMap::new(),
        children: Vec::new(),
        parent,
        coordinate,
        payload,
    }
}
fn coordinate(kind: &str, value: String) -> Coordinate {
    Coordinate {
        kind: kind.into(),
        value,
    }
}

pub(super) fn document(document: &Document, limits: Limits) -> Result<Surface, SurfaceError> {
    if document.bytes().len() > limits.input_bytes {
        return Err(SurfaceError::Limit("input bytes"));
    }
    if limits.depth == 0 || limits.nodes == 0 {
        return Err(SurfaceError::Invalid(
            "nonzero depth and node limits required".into(),
        ));
    }
    let source = from_utf8(document.bytes())
        .map_err(|e| SurfaceError::Parse(e.to_string()))?
        .to_string();
    let profile =
        serde_json::to_vec(&document.profile()).map_err(|e| SurfaceError::Parse(e.to_string()))?;
    let mut digest = Sha256::new();
    digest.update(b"yosoi-index-spike-v2\0");
    digest.update(format!("{:?}\0", document.id()));
    digest.update(&profile);
    digest.update(document.bytes());
    let identity = format!("idx:{:x}", digest.finalize());
    let class = document.class();
    let mut builder = Builder {
        nodes: Vec::new(),
        limits,
    };
    let mut json = None;
    let mut coverage = Coverage {
        complete: true,
        reason: None,
    };
    let representation = match class {
        DocumentClass::SourceHtml => {
            html(&source, &mut builder)?;
            "text/html; normalization=html5"
        }
        DocumentClass::SourceXml => {
            let parsed = roxmltree::Document::parse(&source)
                .map_err(|e| SurfaceError::Parse(e.to_string()))?;
            xml(parsed.root(), None, 0, &mut builder)?;
            "application/xml; source-ranges=exact"
        }
        DocumentClass::SourceJson => {
            // The SDK's JSON parser rejects duplicate keys; Value alone would silently drop them.
            document
                .parse()
                .map_err(|e| SurfaceError::Parse(e.to_string()))?;
            let value: Value =
                serde_json::from_str(&source).map_err(|e| SurfaceError::Parse(e.to_string()))?;
            if value.get("schema").and_then(Value::as_str) == Some("yosoi.network.v1") {
                coverage = Coverage {
                    complete: false,
                    reason: Some(
                        "browser_network_log_window; completeness is unestablished".into(),
                    ),
                };
            }
            json_node(&value, "$".into(), "", None, 0, &mut builder)?;
            json = Some(value);
            "application/json; normalization=serde-json"
        }
        DocumentClass::SourceText => {
            text(&source, &mut builder)?;
            "text/plain; charset=utf-8"
        }
        DocumentClass::RenderedDom | DocumentClass::AccessibilityTree => {
            // Validate the actual SDK wire schema, epoch, graph, and completeness first.
            document
                .parse()
                .map_err(|e| SurfaceError::Parse(e.to_string()))?;
            let value: Value =
                serde_json::from_str(&source).map_err(|e| SurfaceError::Parse(e.to_string()))?;
            if class == DocumentClass::AccessibilityTree {
                let status = value
                    .pointer("/completeness/status")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown");
                coverage = Coverage {
                    complete: status == "complete",
                    reason: if status == "complete" {
                        None
                    } else {
                        Some(
                            value
                                .pointer("/completeness/reason_code")
                                .and_then(Value::as_str)
                                .unwrap_or("unspecified")
                                .into(),
                        )
                    },
                };
            }
            wire(
                &value,
                class == DocumentClass::AccessibilityTree,
                &mut builder,
            )?;
            if class == DocumentClass::RenderedDom {
                "application/vnd.yosoi.rendered-dom.v1+json"
            } else {
                "application/vnd.yosoi.accessibility-tree.v1+json"
            }
        }
    }
    .to_string();
    let mut data = Data {
        original: Some(super::Original::Document {
            id: document.id().clone(),
            profile: document.profile(),
        }),
        identity,
        source,
        input_bytes: document.bytes().len(),
        representation,
        nodes: builder.nodes,
        coverage,
        overview: Vec::new(),
        repeated: BTreeMap::new(),
        json,
        views: Vec::new(),
        #[cfg(any(feature = "browser", feature = "surface-images"))]
        image: None,
    };
    reduce(&mut data, limits.overview_depth)?;
    Ok(Surface {
        data: Arc::new(data),
        response_bytes: None,
    })
}

fn html(source: &str, builder: &mut Builder) -> Result<(), SurfaceError> {
    let dom = parse_document(RcDom::default(), ParseOpts::default()).one(source);
    let mut pending = vec![(dom.document.clone(), None, 0usize, false)];
    let mut ordinal = 0usize;
    let mut template_ordinal = 0usize;
    while let Some((handle, parent, depth, in_template)) = pending.pop() {
        let item = match &handle.data {
            NodeData::Document => node(
                "document",
                "document".into(),
                String::new(),
                parent,
                coordinate("html_document", String::new()),
                Payload::Tree,
            ),
            NodeData::Element { name, attrs, .. } => {
                let counter = if in_template {
                    &mut template_ordinal
                } else {
                    &mut ordinal
                };
                let mut item = node(
                    "element",
                    name.local.to_string(),
                    String::new(),
                    parent,
                    coordinate(
                        if in_template {
                            "html_template_element"
                        } else {
                            "html_element"
                        },
                        counter.to_string(),
                    ),
                    Payload::Tree,
                );
                *counter = counter
                    .checked_add(1)
                    .ok_or(SurfaceError::Limit("HTML element ordinal"))?;
                item.attrs = attrs
                    .borrow()
                    .iter()
                    .map(|a| {
                        let name = a.name.prefix.as_ref().map_or_else(
                            || a.name.local.to_string(),
                            |prefix| format!("{prefix}:{}", a.name.local),
                        );
                        (name, a.value.to_string())
                    })
                    .collect();
                item
            }
            NodeData::Text { contents } => node(
                "text",
                "#text".into(),
                contents.borrow().to_string(),
                parent,
                coordinate("html_text_node", builder.nodes.len().to_string()),
                Payload::Tree,
            ),
            NodeData::Comment { contents } => node(
                "comment",
                "#comment".into(),
                contents.to_string(),
                parent,
                coordinate("html_comment", builder.nodes.len().to_string()),
                Payload::Literal(format!("<!--{contents}-->")),
            ),
            NodeData::Doctype { name, .. } => node(
                "declaration",
                "doctype".into(),
                name.to_string(),
                parent,
                coordinate("html_doctype", builder.nodes.len().to_string()),
                Payload::Literal(format!("<!DOCTYPE {name}>")),
            ),
            NodeData::ProcessingInstruction { .. } => continue,
        };
        let id = builder.push(item, depth)?;
        let next_depth = depth
            .checked_add(1)
            .ok_or(SurfaceError::Limit("tree depth"))?;
        pending.extend(
            handle
                .children
                .borrow()
                .iter()
                .rev()
                .map(|child| (child.clone(), Some(id), next_depth, in_template)),
        );
        if let NodeData::Element {
            template_contents, ..
        } = &handle.data
            && let Some(template) = template_contents.borrow().as_ref()
        {
            pending.extend(
                template
                    .children
                    .borrow()
                    .iter()
                    .rev()
                    .map(|child| (child.clone(), Some(id), next_depth, true)),
            );
        }
    }
    // The RcDom root must survive while queued child handles are traversed.
    drop(dom);
    Ok(())
}

fn xml(
    source: roxmltree::Node<'_, '_>,
    parent: Option<usize>,
    depth: usize,
    builder: &mut Builder,
) -> Result<(), SurfaceError> {
    let range = source.range();
    let name = if source.is_element() {
        let tag = source.tag_name();
        tag.namespace().map_or_else(
            || tag.name().into(),
            |uri| format!("{{{uri}}}{}", tag.name()),
        )
    } else if source.is_text() {
        "#text".into()
    } else {
        "document".into()
    };
    let mut item = node(
        if source.is_text() {
            "text"
        } else if source.is_element() {
            "element"
        } else {
            "document"
        },
        name,
        source
            .text()
            .filter(|_| source.is_text())
            .unwrap_or_default()
            .into(),
        parent,
        coordinate("xml_byte_range", format!("{}..{}", range.start, range.end)),
        Payload::Range(range.start, range.end),
    );
    item.attrs = source
        .attributes()
        .map(|a| {
            (
                a.namespace()
                    .map_or_else(|| a.name().into(), |uri| format!("{{{uri}}}{}", a.name())),
                a.value().into(),
            )
        })
        .collect();
    let id = builder.push(item, depth)?;
    for child in source
        .children()
        .filter(|child| child.is_element() || child.is_text())
    {
        xml(
            child,
            Some(id),
            depth
                .checked_add(1)
                .ok_or(SurfaceError::Limit("XML depth"))?,
            builder,
        )?;
    }
    Ok(())
}

fn json_node(
    value: &Value,
    name: String,
    pointer: &str,
    parent: Option<usize>,
    depth: usize,
    builder: &mut Builder,
) -> Result<(), SurfaceError> {
    let kind = match value {
        Value::Object(_) => "object",
        Value::Array(_) => "array",
        _ => "scalar",
    };
    let text = match value {
        Value::String(s) => s.clone(),
        Value::Object(_) | Value::Array(_) => String::new(),
        other => other.to_string(),
    };
    let id = builder.push(
        node(
            kind,
            name,
            text,
            parent,
            coordinate("json_pointer", pointer.to_string()),
            Payload::Json(pointer.to_string()),
        ),
        depth,
    )?;
    let next = depth
        .checked_add(1)
        .ok_or(SurfaceError::Limit("JSON depth"))?;
    match value {
        Value::Object(object) => {
            for (key, child) in object {
                let escaped = key.replace('~', "~0").replace('/', "~1");
                json_node(
                    child,
                    key.clone(),
                    &format!("{pointer}/{escaped}"),
                    Some(id),
                    next,
                    builder,
                )?;
            }
        }
        Value::Array(array) => {
            for (position, child) in array.iter().enumerate() {
                json_node(
                    child,
                    format!("[{position}]"),
                    &format!("{pointer}/{position}"),
                    Some(id),
                    next,
                    builder,
                )?;
            }
        }
        _ => {}
    }
    Ok(())
}

fn text(source: &str, builder: &mut Builder) -> Result<(), SurfaceError> {
    let root = builder.push(
        node(
            "document",
            "document".into(),
            String::new(),
            None,
            coordinate("text_byte_range", format!("0..{}", source.len())),
            Payload::Range(0, source.len()),
        ),
        0,
    )?;
    // Byte ranges preserve all original content and avoid inventing semantic headings.
    let mut start = 0usize;
    while start < source.len() {
        let proposed = start.saturating_add(2048).min(source.len());
        let mut end = proposed;
        while !source.is_char_boundary(end) {
            end = end
                .checked_sub(1)
                .ok_or(SurfaceError::Limit("UTF-8 boundary"))?;
        }
        if end == start {
            return Err(SurfaceError::Invalid("text chunk made no progress".into()));
        }
        let content = source.get(start..end).ok_or(SurfaceError::Unknown)?;
        builder.push(
            node(
                "text",
                format!("bytes {start}..{end}"),
                content.into(),
                Some(root),
                coordinate("text_byte_range", format!("{start}..{end}")),
                Payload::Range(start, end),
            ),
            1,
        )?;
        start = end;
    }
    Ok(())
}

fn wire(value: &Value, ax: bool, builder: &mut Builder) -> Result<(), SurfaceError> {
    let records = value
        .get("nodes")
        .and_then(Value::as_array)
        .ok_or_else(|| SurfaceError::Parse("snapshot has no nodes".into()))?;
    let key = |id: &Value| {
        if ax {
            id.as_str().map(str::to_string)
        } else {
            id.as_u64().map(|id| id.to_string())
        }
    };
    let mut by_id = BTreeMap::new();
    for record in records {
        let id = record
            .get("id")
            .and_then(key)
            .ok_or(SurfaceError::Unknown)?;
        by_id.insert(id, record);
    }
    let root = value
        .get("root")
        .and_then(key)
        .ok_or(SurfaceError::Unknown)?;
    let mut pending = vec![(root, None, 0usize)];
    while let Some((wire_id, parent, depth)) = pending.pop() {
        let record = by_id.get(&wire_id).ok_or(SurfaceError::Unknown)?;
        let kind = if ax {
            "accessibility"
        } else {
            record
                .get("kind")
                .and_then(Value::as_str)
                .unwrap_or("unknown")
        };
        let name = record
            .get(if ax { "role" } else { "tag_name" })
            .and_then(Value::as_str)
            .unwrap_or(kind)
            .to_string();
        let text = if ax {
            let mut parts = Vec::new();
            for key in ["accessible_name", "text"] {
                if let Some(value) = record.get(key).and_then(Value::as_str)
                    && !value.is_empty()
                    && !parts.contains(&value)
                {
                    parts.push(value);
                }
            }
            parts.join(" ")
        } else {
            record
                .get("value")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .into()
        };
        let mut item = node(
            kind,
            name,
            text,
            parent,
            coordinate(if ax { "accessibility_node" } else { "dom_node" }, wire_id),
            Payload::Literal(
                serde_json::to_string(record).map_err(|e| SurfaceError::Parse(e.to_string()))?,
            ),
        );
        if ax {
            if let Some(states) = record.get("states").and_then(Value::as_object) {
                item.attrs = states
                    .iter()
                    .map(|(k, v)| (k.clone(), v.to_string()))
                    .collect();
            }
        } else if let Some(attrs) = record.get("attributes").and_then(Value::as_array) {
            for attribute in attrs {
                if let (Some(name), Some(value)) = (
                    attribute.get("name").and_then(Value::as_str),
                    attribute.get("value").and_then(Value::as_str),
                ) {
                    let namespace = attribute
                        .get("namespace_uri")
                        .and_then(Value::as_str)
                        .unwrap_or_default();
                    let key = if namespace.is_empty() {
                        name.into()
                    } else {
                        format!("{{{namespace}}}{name}")
                    };
                    item.attrs.insert(key, value.into());
                }
            }
        }
        let id = builder.push(item, depth)?;
        let next = depth
            .checked_add(1)
            .ok_or(SurfaceError::Limit("snapshot depth"))?;
        let children = record
            .get("children")
            .and_then(Value::as_array)
            .ok_or(SurfaceError::Unknown)?;
        for child in children.iter().rev() {
            pending.push((key(child).ok_or(SurfaceError::Unknown)?, Some(id), next));
        }
    }
    Ok(())
}

pub(super) fn reduce(data: &mut Data, depth_limit: usize) -> Result<(), SurfaceError> {
    let mut pending = vec![(0usize, 0usize)];
    while let Some((id, depth)) = pending.pop() {
        let item = data.nodes.get(id).ok_or(SurfaceError::Unknown)?;
        if matches!(item.name.as_str(), "script" | "style")
            || item.kind == "text" && item.text.trim().is_empty()
        {
            continue;
        }
        data.overview.push(id);
        let members: Vec<_> = item
            .children
            .iter()
            .copied()
            .filter(|id| {
                data.nodes
                    .get(*id)
                    .is_some_and(|n| n.kind != "text" || !n.text.trim().is_empty())
            })
            .collect();
        let shape = |id: usize| -> Option<String> {
            let node = data.nodes.get(id)?;
            let children = node
                .children
                .iter()
                .filter_map(|i| data.nodes.get(*i))
                .filter(|n| n.kind != "text" || !n.text.trim().is_empty())
                .map(|n| {
                    if n.name.starts_with('[') {
                        "[]"
                    } else {
                        &n.name
                    }
                })
                .collect::<Vec<_>>()
                .join(",");
            Some(format!(
                "{}:{}:{children}",
                node.kind,
                if node.name.starts_with('[') {
                    "[]"
                } else {
                    &node.name
                }
            ))
        };
        let repeated = members.len() >= 3
            && members
                .first()
                .and_then(|first| shape(*first))
                .is_some_and(|first| members.iter().all(|id| shape(*id).as_ref() == Some(&first)));
        if repeated {
            data.repeated.insert(id, members);
            continue;
        }
        if depth >= depth_limit {
            continue;
        }
        let next = depth
            .checked_add(1)
            .ok_or(SurfaceError::Limit("overview depth"))?;
        pending.extend(members.into_iter().rev().map(|child| (child, next)));
    }
    Ok(())
}

pub(super) fn serialize(nodes: &[Node], root: usize) -> Result<String, SurfaceError> {
    enum Part {
        Open(usize, bool),
        Close(String),
    }
    let mut pending = vec![Part::Open(root, false)];
    let mut output = String::new();
    while let Some(part) = pending.pop() {
        match part {
            Part::Close(name) => {
                output.push_str("</");
                output.push_str(&name);
                output.push('>');
            }
            Part::Open(id, raw) => {
                let node = nodes.get(id).ok_or(SurfaceError::Unknown)?;
                if let Payload::Literal(content) = &node.payload {
                    output.push_str(content);
                    continue;
                }
                if node.kind == "text" {
                    output.push_str(&if raw {
                        node.text.clone()
                    } else {
                        escape(&node.text, false)
                    });
                    continue;
                }
                if node.kind == "element" {
                    output.push('<');
                    output.push_str(&node.name);
                    for (name, value) in &node.attrs {
                        output.push(' ');
                        output.push_str(name);
                        output.push_str("=\"");
                        output.push_str(&escape(value, true));
                        output.push('"');
                    }
                    output.push('>');
                    if matches!(
                        node.name.as_str(),
                        "area"
                            | "base"
                            | "br"
                            | "col"
                            | "embed"
                            | "hr"
                            | "img"
                            | "input"
                            | "link"
                            | "meta"
                            | "param"
                            | "source"
                            | "track"
                            | "wbr"
                    ) {
                        continue;
                    }
                    pending.push(Part::Close(node.name.clone()));
                }
                let raw = matches!(node.name.as_str(), "script" | "style");
                pending.extend(node.children.iter().rev().map(|id| Part::Open(*id, raw)));
            }
        }
    }
    Ok(output)
}
fn escape(value: &str, attribute: bool) -> String {
    let mut value = value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;");
    if attribute {
        value = value.replace('"', "&quot;");
    }
    value
}
