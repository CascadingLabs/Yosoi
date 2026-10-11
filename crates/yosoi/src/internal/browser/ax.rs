//! Pure helpers for turning a raw `Accessibility.getFullAXTree` node array
//! into a compact, readable `role "name"` outline.
//!
//! The raw array is a flat list linked by `childIds` and `parentId`. Keeping
//! this conversion in the engine gives every Yosoi browser workflow one
//! implementation.

use std::{collections::HashMap, fmt::Write as _};

use serde_json::Value;

/// Pull the inner `.value` string out of an AXValue-wrapped field, or "".
fn ax_value<'a>(node: &'a Value, key: &str) -> &'a str {
    node.get(key)
        .and_then(|v| v.get("value"))
        .and_then(Value::as_str)
        .unwrap_or("")
}

fn ax_ignored(node: &Value) -> bool {
    node.get("ignored")
        .and_then(Value::as_bool)
        .unwrap_or(false)
}

/// Roles that carry no standalone meaning — collapsed out of the compact
/// outline (their text folds into an ancestor's accessible name).
fn ax_is_noise(role: &str, name: &str) -> bool {
    matches!(
        role,
        "StaticText" | "InlineTextBox" | "LineBreak" | "none" | "presentation"
    ) || (role == "generic" && name.is_empty())
}

/// Returns `(total_nodes, named_nodes)`.
///
/// A named node is non-ignored and carries a non-empty accessible name. A low
/// named-to-total ratio signals a thin AX tree and can trigger another
/// addressing strategy.
#[must_use]
pub fn richness(nodes: &[Value]) -> (usize, usize) {
    let named = nodes
        .iter()
        .filter(|n| !ax_ignored(n) && !ax_value(n, "name").is_empty())
        .count();
    (nodes.len(), named)
}

/// Reconstruct the hierarchy from the flat node list and render a pruned,
/// indented `role "name"` outline. Skipped nodes don't consume an indent
/// level, keeping the outline tight.
#[must_use]
pub fn compact_outline(nodes: &[Value]) -> String {
    let by_id: HashMap<&str, &Value> = nodes
        .iter()
        .filter_map(|n| n.get("nodeId").and_then(Value::as_str).map(|id| (id, n)))
        .collect();
    let mut out = String::new();
    for node in nodes {
        let is_root = node
            .get("parentId")
            .and_then(Value::as_str)
            .is_none_or(|p| !by_id.contains_key(p));
        if is_root && let Some(id) = node.get("nodeId").and_then(Value::as_str) {
            walk(id, 0, &by_id, &mut out);
        }
    }
    out
}

fn walk(id: &str, depth: usize, by_id: &HashMap<&str, &Value>, out: &mut String) {
    let Some(node) = by_id.get(id) else { return };
    let role = ax_value(node, "role");
    let name = ax_value(node, "name");
    let emit = !ax_ignored(node) && !ax_is_noise(role, name);
    let child_depth = if emit {
        for _ in 0..depth {
            out.push_str("  ");
        }
        if name.is_empty() {
            out.push_str(role);
        } else {
            let _ = write!(out, "{role} {name:?}");
        }
        out.push('\n');
        depth.saturating_add(1)
    } else {
        depth
    };
    if let Some(children) = node.get("childIds").and_then(Value::as_array) {
        for child in children.iter().filter_map(Value::as_str) {
            walk(child, child_depth, by_id, out);
        }
    }
}

#[cfg(test)]
mod tests {
    //! Pure-logic tests over synthetic CDP node lists — no browser.
    use serde_json::{Value, json};

    use super::{ax_is_noise, compact_outline, richness};

    fn node(id: &str, parent: Option<&str>, role: &str, name: &str, children: &[&str]) -> Value {
        json!({
            "nodeId": id,
            "ignored": false,
            "role": { "type": "role", "value": role },
            "name": { "type": "computedString", "value": name },
            "parentId": parent,
            "childIds": children,
        })
    }

    #[test]
    fn renders_role_and_name_indented_by_depth() {
        let nodes = vec![
            node("1", None, "RootWebArea", "Doc", &["2"]),
            node("2", Some("1"), "button", "Load more", &[]),
        ];
        assert_eq!(
            compact_outline(&nodes),
            "RootWebArea \"Doc\"\n  button \"Load more\"\n"
        );
    }

    #[test]
    fn collapses_text_noise_without_consuming_indent() {
        let nodes = vec![
            node("1", None, "RootWebArea", "", &["2"]),
            node("2", Some("1"), "button", "Click me", &["3", "4"]),
            node("3", Some("2"), "StaticText", "Click me", &[]),
            node("4", Some("2"), "InlineTextBox", "Click me", &[]),
        ];
        assert_eq!(
            compact_outline(&nodes),
            "RootWebArea\n  button \"Click me\"\n"
        );
    }

    #[test]
    fn skips_ignored_nodes_but_keeps_descendants() {
        let nodes = vec![
            node("1", None, "RootWebArea", "", &["2"]),
            json!({
                "nodeId": "2", "ignored": true,
                "role": { "type": "role", "value": "generic" },
                "parentId": "1", "childIds": ["3"],
            }),
            node("3", Some("2"), "link", "Home", &[]),
        ];
        assert_eq!(compact_outline(&nodes), "RootWebArea\n  link \"Home\"\n");
    }

    #[test]
    fn unnamed_generic_is_noise_named_generic_is_not() {
        assert!(ax_is_noise("generic", ""));
        assert!(!ax_is_noise("generic", "Sidebar"));
        assert!(ax_is_noise("StaticText", "anything"));
        assert!(!ax_is_noise("button", ""));
    }

    #[test]
    fn handles_orphans_as_additional_roots() {
        let nodes = vec![
            node("1", None, "RootWebArea", "", &[]),
            node("99", Some("missing"), "button", "Orphan", &[]),
        ];
        assert!(compact_outline(&nodes).contains("button \"Orphan\""));
    }

    #[test]
    fn richness_counts_named_non_ignored_nodes() {
        let nodes = vec![
            node("1", None, "RootWebArea", "Doc", &[]),
            node("2", None, "generic", "", &[]),
            json!({"nodeId": "3", "ignored": true,
                   "name": {"type":"computedString","value":"hidden"}}),
        ];
        // 3 total; only node 1 is non-ignored AND named.
        assert_eq!(richness(&nodes), (3, 1));
    }
}
