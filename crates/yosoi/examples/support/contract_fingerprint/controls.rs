//! Counterexamples distinguish structural eligibility, runtime validity and truth.
use super::{
    Result, fail,
    recipe::Recipe,
    structure::{Dom, selected_nodes},
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use yosoi::documents::Document;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(super) enum Mutation {
    MissingPrice,
    WrongPrice,
    ReorderedFacts,
    DuplicatePrice,
    ChangedWrapper,
    OutsideDecoy,
}

pub(super) fn mutate(document: &Document, recipe: &Recipe, mutation: Mutation) -> Result<Document> {
    let mut dom = Dom::read(document)?;
    let located = recipe.locate(document, &recipe.plan()?)?;
    let selected = selected_nodes(&located, dom.document_epoch)?;
    let price = *selected
        .get("price")
        .ok_or_else(|| super::error("price evidence missing"))?;
    match mutation {
        Mutation::MissingPrice => {
            let mut removed = BTreeSet::new();
            let mut pending = vec![price];
            while let Some(id) = pending.pop() {
                if !removed.insert(id) {
                    return fail("cycle in removal");
                }
                pending.extend(dom.node(id)?.children.iter().copied());
            }
            dom.nodes.retain(|node| !removed.contains(&node.id));
            for node in &mut dom.nodes {
                node.children.retain(|id| !removed.contains(id));
            }
        }
        Mutation::WrongPrice => {
            let children = dom.node(price)?.children.clone();
            let text = dom
                .nodes
                .iter_mut()
                .find(|node| children.contains(&node.id) && node.kind == "text")
                .ok_or_else(|| super::error("price text missing"))?;
            text.value = Some("$999.00".into());
        }
        Mutation::ReorderedFacts => {
            let facts = dom
                .nodes
                .iter_mut()
                .find(|node| has_class(node, "shop-product-facts"))
                .ok_or_else(|| super::error("facts region missing"))?;
            facts.children.reverse();
        }
        Mutation::DuplicatePrice => {
            let lede = dom
                .nodes
                .iter_mut()
                .find(|node| has_class(node, "shop-product-lede"))
                .ok_or_else(|| super::error("lede missing"))?;
            let class = lede
                .attributes
                .iter_mut()
                .flatten()
                .find(|a| a.name == "class")
                .ok_or_else(|| super::error("lede class missing"))?;
            class.value = "shop-detail-price".into();
        }
        Mutation::ChangedWrapper => {
            let parent = dom
                .node(price)?
                .parent
                .ok_or_else(|| super::error("price parent missing"))?;
            let wrapper = dom
                .nodes
                .iter_mut()
                .find(|node| node.id == parent)
                .ok_or_else(|| super::error("wrapper missing"))?;
            wrapper.tag_name = Some("aside".into());
        }
        Mutation::OutsideDecoy => {
            let root = *selected
                .get("root")
                .ok_or_else(|| super::error("root missing"))?;
            let outside = dom
                .node(root)?
                .parent
                .ok_or_else(|| super::error("root parent missing"))?;
            let lede = dom
                .nodes
                .iter()
                .find(|node| has_class(node, "shop-product-lede"))
                .ok_or_else(|| super::error("lede missing"))?
                .id;
            let old_parent = dom
                .node(lede)?
                .parent
                .ok_or_else(|| super::error("lede parent missing"))?;
            for node in &mut dom.nodes {
                if node.id == old_parent {
                    node.children.retain(|id| *id != lede);
                }
                if node.id == outside {
                    node.children.push(lede);
                }
                if node.id == lede {
                    node.parent = Some(outside);
                    for a in node
                        .attributes
                        .iter_mut()
                        .flatten()
                        .filter(|a| a.name == "class")
                    {
                        a.value = "shop-detail-price".into();
                    }
                }
            }
        }
    }
    let mutated = dom.document(document.id().as_str())?;
    mutated.parse()?;
    Ok(mutated)
}

fn has_class(node: &super::structure::Node, class: &str) -> bool {
    node.attributes
        .iter()
        .flatten()
        .any(|a| a.name == "class" && a.value.split_whitespace().any(|v| v == class))
}
