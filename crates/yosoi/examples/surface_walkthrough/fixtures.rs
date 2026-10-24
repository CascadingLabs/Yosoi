use serde_json::json;
use std::{error::Error, fmt::Write};
use yosoi::documents::{Document, DocumentEpoch};

pub fn documents(count: usize) -> Result<Vec<Document>, Box<dyn Error>> {
    let mut html = String::from("<!doctype html><main><h1>Collection</h1><div>");
    let mut xml = String::from("<collection xmlns='urn:objects'>");
    let mut text = String::new();
    let mut records = Vec::new();
    let mut dom_nodes = vec![
        json!({"kind":"document","id":1,"parent":null,"children":[2]}),
        json!({"kind":"element","id":2,"parent":1,"children":[],"namespace_uri":"http://www.w3.org/1999/xhtml","tag_name":"main","attributes":[]}),
    ];
    let mut dom_children = Vec::new();
    let mut ax_nodes = Vec::new();
    let mut ax_children = Vec::new();
    for n in 0..count {
        let name = if n == count.checked_div(2).unwrap_or_default() {
            "Needle lamp".into()
        } else {
            format!("Object {n}")
        };
        write!(
            html,
            "<article data-key='item-{n}'><h2>{name}</h2><p>Material: ceramic</p></article>"
        )?;
        write!(
            xml,
            "<item key='item-{n}'><name>{name}</name><material>ceramic</material></item>"
        )?;
        writeln!(text, "Item {n}: {name}; material ceramic.")?;
        records.push(json!({"id":format!("item-{n}"),"name":name,"material":"ceramic"}));
        let element = n.saturating_mul(2).saturating_add(3);
        let child = element.saturating_add(1);
        dom_children.push(element);
        dom_nodes.push(json!({"kind":"element","id":element,"parent":2,"children":[child],"namespace_uri":"http://www.w3.org/1999/xhtml","tag_name":"article","attributes":[]}));
        dom_nodes
            .push(json!({"kind":"text","id":child,"parent":element,"children":[],"value":name}));
        let ax_id = format!("item-{n}");
        ax_children.push(ax_id.clone());
        ax_nodes.push(json!({"id":ax_id,"parent":"root","children":[],"ignored":false,"role":"article","accessible_name":name,"text":null,"states":{}}));
    }
    if let Some(main) = dom_nodes.get_mut(1) {
        main["children"] = json!(dom_children);
    }
    ax_nodes.insert(0,json!({"id":"root","parent":null,"children":ax_children,"ignored":false,"role":"RootWebArea","accessible_name":null,"text":null,"states":{}}));
    html.push_str("</div><p>Unique delivery prose remains reachable.</p></main>");
    xml.push_str("</collection>");
    Ok(vec![
        Document::html("collection.html", html.into_bytes())?,
        Document::xml("collection.xml", xml.into_bytes())?,
        Document::json(
            "collection.json",
            serde_json::to_vec(&json!({"records":records}))?,
        )?,
        Document::text("collection.txt", text.into_bytes())?,
        Document::rendered_dom(
            "collection.dom",
            DocumentEpoch::try_from(1)?,
            serde_json::to_vec(
                &json!({"schema":"yosoi.rendered-dom.v1","document_epoch":1,"tree_model":"document_light_dom","root":1,"nodes":dom_nodes}),
            )?,
        )?,
        Document::accessibility_tree(
            "collection.ax",
            DocumentEpoch::try_from(1)?,
            serde_json::to_vec(
                &json!({"schema":"yosoi.accessibility-tree.v1","document_epoch":1,"root":"root","completeness":{"status":"complete"},"nodes":ax_nodes}),
            )?,
        )?,
    ])
}
