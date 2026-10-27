//! Experiment-local adapter over the versioned public rendered-DOM wire format.
use super::{Result, fail};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use yosoi::{
    documents::{Document, DocumentClass},
    locators::{Completeness, LocateOutcome, NativeCoordinate},
};

#[derive(Clone, Debug, Deserialize, Serialize)]
pub(super) struct Attribute {
    pub namespace_uri: String,
    pub name: String,
    pub value: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub(super) struct Node {
    pub id: u64,
    pub parent: Option<u64>,
    pub children: Vec<u64>,
    pub kind: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub namespace_uri: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tag_name: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub attributes: Option<Vec<Attribute>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub value: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub(super) struct Dom {
    pub schema: String,
    pub document_epoch: u64,
    pub tree_model: String,
    pub root: u64,
    pub nodes: Vec<Node>,
}

impl Dom {
    pub fn read(document: &Document) -> Result<Self> {
        if document.class() != DocumentClass::RenderedDom || document.byte_len() > 2_000_000 {
            return fail("expected a rendered DOM of at most 2 MB");
        }
        // Validate the exact same snapshot through the SDK before inspecting its wire nodes.
        document.parse()?;
        Ok(serde_json::from_slice(document.bytes())?)
    }

    pub fn node(&self, id: u64) -> Result<&Node> {
        self.nodes
            .iter()
            .find(|node| node.id == id)
            .ok_or_else(|| super::error("node absent from snapshot"))
    }

    pub fn document(&self, id: &str) -> Result<Document> {
        Ok(Document::rendered_dom(
            id,
            self.document_epoch.try_into()?,
            serde_json::to_vec(self)?,
        )?)
    }

    pub fn signature(&self, selected: u64, root: u64) -> Result<BTreeSet<String>> {
        let index: BTreeMap<u64, &Node> = self.nodes.iter().map(|node| (node.id, node)).collect();
        let mut relation = Vec::new();
        let mut current = selected;
        // All relations stop at the selected contract root, never at the document root.
        for _ in 0..64 {
            let node = index
                .get(&current)
                .ok_or_else(|| super::error("missing ancestor"))?;
            relation.push(symbol(node));
            if current == root {
                break;
            }
            current = node
                .parent
                .ok_or_else(|| super::error("field lies outside contract root"))?;
        }
        if current != root {
            return fail("field-to-root depth exceeds 64");
        }
        relation.reverse();
        let mut features = BTreeSet::from([format!("relation:{}", relation.join("/"))]);
        let mut pending = vec![(selected, Vec::<String>::new())];
        let mut visits = 0_u32;
        while let Some((id, mut path)) = pending.pop() {
            visits = visits
                .checked_add(1)
                .ok_or_else(|| super::error("visit count overflow"))?;
            if visits > 10_000 {
                return fail("selected component exceeds visit budget");
            }
            let node = index
                .get(&id)
                .ok_or_else(|| super::error("missing descendant"))?;
            if node.kind != "element" {
                continue;
            }
            path.push(symbol(node));
            features.insert(format!("path:{}", path.join("/")));
            if path.len() < 3 {
                for child in &node.children {
                    pending.push((*child, path.clone()));
                }
            }
        }
        Ok(features)
    }
}

fn symbol(node: &Node) -> String {
    // Attribute names only: no CSS class values, IDs, URLs, text or product values.
    let names: BTreeSet<&str> = node
        .attributes
        .iter()
        .flatten()
        .map(|a| a.name.as_str())
        .collect();
    format!(
        "{}[{}]",
        node.tag_name.as_deref().unwrap_or("#node"),
        names.into_iter().collect::<Vec<_>>().join(",")
    )
}

pub(super) fn selected_nodes(outcome: &LocateOutcome, epoch: u64) -> Result<BTreeMap<String, u64>> {
    let LocateOutcome::Matched { result } = outcome else {
        return fail("locator did not produce complete matches");
    };
    let [root] = result.regions() else {
        return fail("exactly one selected contract root required");
    };
    let NativeCoordinate::RenderedDom(root_coordinate) = root.coordinate() else {
        return fail("non-DOM root");
    };
    if root_coordinate.document_epoch().get() != epoch {
        return fail("root epoch mismatch");
    }
    let mut selected = BTreeMap::from([("root".to_owned(), root_coordinate.node_id().get())]);
    for finding in result.findings() {
        if finding.completeness() != &Completeness::Complete {
            return fail("partial field evidence");
        }
        let NativeCoordinate::RenderedDom(coordinate) = finding.coordinate() else {
            return fail("non-DOM evidence");
        };
        if coordinate.document_epoch().get() != epoch {
            return fail("snapshot epoch mismatch");
        }
        if selected
            .insert(
                finding.output_id().as_str().to_owned(),
                coordinate.node_id().get(),
            )
            .is_some()
        {
            return fail("field cardinality is not exactly one");
        }
    }
    Ok(selected)
}

impl Dom {
    pub fn text(&self, selected: u64) -> Result<String> {
        let mut pending = vec![selected];
        let mut output = Vec::new();
        let mut visits = 0_u32;
        while let Some(id) = pending.pop() {
            visits = visits
                .checked_add(1)
                .ok_or_else(|| super::error("text visit overflow"))?;
            if visits > 10_000 {
                return fail("text visit budget exceeded");
            }
            let node = self.node(id)?;
            if let Some(value) = &node.value {
                output.push(value.as_str());
            }
            pending.extend(node.children.iter().rev().copied());
        }
        Ok(output
            .join(" ")
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" "))
    }
}
