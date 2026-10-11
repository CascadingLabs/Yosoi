use html5ever::{
    ParseOpts, parse_document,
    tendril::TendrilSink,
    tree_builder::{TreeBuilderOpts, TreeSink},
};

use super::super::{HtmlNode, node::HtmlNodeKind};
use super::CompactHtmlSink;
use crate::internal::documents::html::HtmlParseError;

const SELECTED_OPTIONS: &str = concat!(
    "<template><i>template</i></template>",
    "<select><button><selectedcontent></selectedcontent></button>",
    "<option selected><span class='choice'>Alpha</span></option></select>",
);

const NESTED_SELECTEDCONTENT: &str = concat!(
    "<select><button>",
    "<span><selectedcontent id='preorder'></selectedcontent></span>",
    "<selectedcontent id='shallow'></selectedcontent>",
    "</button><option selected><span class='choice'>Alpha</span></option></select>",
);

fn parse_sink(source: &str) -> CompactHtmlSink {
    let options = ParseOpts {
        tree_builder: TreeBuilderOpts {
            scripting_enabled: false,
            ..TreeBuilderOpts::default()
        },
        ..ParseOpts::default()
    };
    parse_document(CompactHtmlSink::default(), options).one(source)
}

fn sink_with_replaced_selectedcontent_clones() -> CompactHtmlSink {
    let sink = parse_sink(SELECTED_OPTIONS);
    let option = {
        let nodes = sink.nodes.borrow();
        nodes
            .iter()
            .enumerate()
            .find_map(|(id, node)| match &node.kind {
                HtmlNodeKind::Element {
                    name, attributes, ..
                } if name.local.as_ref() == "option"
                    && attributes.iter().any(|attribute| {
                        attribute
                            .name
                            .local
                            .as_ref()
                            .eq_ignore_ascii_case("selected")
                    }) =>
                {
                    Some(id)
                }
                _ => None,
            })
            .expect("selected option in fixture")
    };

    for _ in 0..8 {
        TreeSink::maybe_clone_an_option_into_selectedcontent(&sink, &option);
    }
    sink
}

#[test]
fn selectedcontent_cloning_uses_first_preorder_descendant() {
    let sink = parse_sink(NESTED_SELECTEDCONTENT);
    let nodes = sink.nodes.borrow();
    let find_selectedcontent = |id_value: &str| {
        nodes.iter().enumerate().find_map(|(id, node)| {
            let HtmlNodeKind::Element {
                name, attributes, ..
            } = &node.kind
            else {
                return None;
            };
            (name.local.as_ref() == "selectedcontent"
                && attributes.iter().any(|attribute| {
                    attribute.name.local.as_ref() == "id" && attribute.value.as_ref() == id_value
                }))
            .then_some(id)
        })
    };
    let preorder = find_selectedcontent("preorder").expect("nested selectedcontent fixture");
    let shallow = find_selectedcontent("shallow").expect("shallow selectedcontent fixture");

    let cloned_option_child = nodes
        .get(preorder)
        .and_then(|node| node.first_child.get())
        .and_then(|id| nodes.get(id))
        .expect("first selectedcontent receives the selected option clone");
    assert!(matches!(
        &cloned_option_child.kind,
        HtmlNodeKind::Element { name, attributes, .. }
            if name.local.as_ref() == "span"
                && attributes.iter().any(|attribute| {
                    attribute.name.local.as_ref() == "class"
                        && attribute.value.as_ref() == "choice"
                })
    ));
    assert!(
        nodes
            .get(shallow)
            .is_some_and(|node| node.first_child.is_absent()),
        "later shallow selectedcontent must remain empty"
    );
}

fn reachable_node_count(nodes: &[HtmlNode]) -> usize {
    let mut seen = vec![false; nodes.len()];
    let mut pending = vec![0_usize];
    while let Some(id) = pending.pop() {
        let Some(visited) = seen.get_mut(id) else {
            continue;
        };
        if *visited {
            continue;
        }
        *visited = true;
        let Some(node) = nodes.get(id) else {
            continue;
        };
        let mut child = node.first_child.get();
        while let Some(child_id) = child {
            pending.push(child_id);
            child = nodes.get(child_id).and_then(|child| child.next.get());
        }
        if let HtmlNodeKind::Element {
            template: Some(template),
            ..
        } = &node.kind
        {
            pending.push(*template);
        }
    }
    seen.into_iter().filter(|visited| *visited).count()
}

fn arena_slots(sink: &CompactHtmlSink) -> (u64, u64, u64) {
    let nodes = sink.nodes.borrow();
    let allocated = u64::try_from(nodes.len()).expect("fixture node count fits u64");
    let reachable =
        u64::try_from(reachable_node_count(&nodes)).expect("fixture reachable node count fits u64");
    let template_fragments = nodes
        .iter()
        .filter(|node| matches!(&node.kind, HtmlNodeKind::Document))
        .count()
        .saturating_sub(1);
    let template_fragments =
        u64::try_from(template_fragments).expect("fixture template count fits u64");
    (allocated, reachable, template_fragments)
}

#[test]
fn node_count_includes_replaced_selectedcontent_clones_and_template_fragments() {
    let sink = sink_with_replaced_selectedcontent_clones();
    let (allocated, reachable, template_fragments) = arena_slots(&sink);
    assert!(
        allocated > reachable,
        "fixture should leave replaced clones in the arena"
    );
    assert!(
        template_fragments > 0,
        "fixture should include a template fragment"
    );

    let tree = sink
        .into_tree(64, u64::MAX)
        .expect("tree fits the unlimited node budget");
    assert_eq!(tree.node_count(), allocated);
    assert_eq!(
        usize::try_from(tree.node_count()).expect("fixture node count fits usize"),
        tree.nodes.len()
    );
}

#[test]
fn max_nodes_rejects_replaced_selectedcontent_clones() {
    let sink = sink_with_replaced_selectedcontent_clones();
    let (allocated, reachable, template_fragments) = arena_slots(&sink);
    assert!(
        allocated > reachable,
        "fixture should leave replaced clones in the arena"
    );
    assert!(
        template_fragments > 0,
        "fixture should include a template fragment"
    );

    let result = sink.into_tree(64, reachable);
    assert!(matches!(
        result,
        Err(HtmlParseError::NodeLimitExceeded { maximum, observed })
            if maximum == reachable && observed == allocated
    ));
}
