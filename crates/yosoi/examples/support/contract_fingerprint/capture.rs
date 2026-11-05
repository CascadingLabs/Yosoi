//! Capture rendered HTML after explicit readiness, then normalize the immutable
//! snapshot into the public rendered-DOM schema. IDs are snapshot-local, not CDP IDs.
use super::Result;
use html5ever::{ParseOpts, parse_document, tendril::TendrilSink, tree_builder::TreeBuilderOpts};
use markup5ever_rcdom::{NodeData, RcDom};
use serde_json::{Map, Value, json};
use std::{error::Error, fs, io, path::Path};
use yosoi::{
    Archive, automation_record::OperationStatus, documents::Document, flow::Condition, session,
};

#[expect(
    clippy::significant_drop_tightening,
    reason = "Work::release consumes Work; the suggested drop after release is a use-after-move."
)]
pub async fn capture(output: &Path, id: &str) -> Result {
    if ![
        "obj-001", "obj-002", "obj-003", "obj-004", "obj-005", "obj-006",
    ]
    .contains(&id)
    {
        return Err(io::Error::other("unknown fixture product").into());
    }
    fs::create_dir_all(output)?;
    let browser = session::new().acquire().await?;
    let work = browser.work().await?;
    let captured = async {
        let navigation = work.navigate(&format!("https://qscrape.dev/eshop/javascript/product/{id}/")).await?;
        if navigation.status != OperationStatus::Observed { return Err(io::Error::other("navigation failed").into()); }
        let readiness = work.wait_until(&Condition::Exists { selector: "main h1".into() }, 15_000).await?;
        if readiness.status != OperationStatus::Observed { return Err(io::Error::other("product heading did not render").into()); }
        let observation = work.observe().await?;
        let html = observation.html.as_deref().ok_or_else(|| io::Error::other("no rendered HTML"))?;
        let document = normalize(id, observation.document_epoch, html)?;
        let archive = Archive::open(output.join("archive")).await?;
        let reference = archive.write_document(&document).await?;
        fs::write(output.join(format!("{id}.ref.json")), serde_json::to_vec_pretty(&reference)?)?;
        fs::write(output.join(format!("{id}.dom.json")), document.bytes())?;
        fs::write(output.join(format!("{id}.capture.json")), serde_json::to_vec_pretty(&json!({
            "sdk":env!("CARGO_PKG_VERSION"), "navigation":navigation, "readiness":readiness, "observation":observation
        }))?)?;
        println!("{id}: {} ready DOM bytes archived", document.byte_len());
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    }.await;
    let released = work.release().await;
    let closed = browser.close().await;
    drop(browser);
    captured?;
    released?;
    closed?;
    Ok(())
}

fn normalize(id: &str, epoch: u64, html: &str) -> Result<Document> {
    if html.len() > 2_000_000 {
        return Err(io::Error::other("HTML snapshot exceeds 2 MB").into());
    }
    let options = ParseOpts {
        tree_builder: TreeBuilderOpts {
            scripting_enabled: true,
            ..TreeBuilderOpts::default()
        },
        ..ParseOpts::default()
    };
    let dom = parse_document(RcDom::default(), options).one(html);
    let mut nodes = vec![json!({"id":1,"parent":null,"kind":"document","children":[]})];
    let mut pending = Vec::new();
    for child in dom.document.children.borrow().iter().rev() {
        pending.push((child.clone(), 0_usize, 0_u32));
    }
    while let Some((handle, parent_index, depth)) = pending.pop() {
        if nodes.len() > 10_000 || depth > 64 {
            return Err(io::Error::other("DOM normalization budget exceeded").into());
        }
        let index = nodes.len();
        let node_id = u64::try_from(index)?
            .checked_add(1)
            .ok_or_else(|| io::Error::other("node ID overflow"))?;
        let parent = nodes
            .get_mut(parent_index)
            .ok_or_else(|| io::Error::other("missing parent"))?;
        let parent_id = parent
            .get("id")
            .cloned()
            .ok_or_else(|| io::Error::other("missing parent ID"))?;
        let mut node = Map::new();
        node.insert("id".into(), json!(node_id));
        node.insert("parent".into(), parent_id);
        node.insert("children".into(), json!([]));
        match &handle.data {
            NodeData::Element { name, attrs, .. } => {
                node.insert("kind".into(), json!("element"));
                node.insert("namespace_uri".into(), json!(name.ns.as_ref()));
                node.insert("tag_name".into(), json!(name.local.as_ref()));
                let mut attributes: Vec<_> = attrs
                    .borrow()
                    .iter()
                    .map(|a| {
                        (
                            a.name.ns.to_string(),
                            a.name.local.to_string(),
                            a.value.to_string(),
                        )
                    })
                    .collect();
                attributes.sort();
                node.insert("attributes".into(), Value::Array(attributes.into_iter().map(|(ns, name, value)| json!({"namespace_uri":ns,"name":name,"value":value})).collect()));
            }
            NodeData::Text { contents } => {
                node.insert("kind".into(), json!("text"));
                node.insert("value".into(), json!(contents.borrow().as_ref()));
            }
            _ => continue,
        }
        parent
            .get_mut("children")
            .and_then(Value::as_array_mut)
            .ok_or_else(|| io::Error::other("missing children"))?
            .push(json!(node_id));
        nodes.push(Value::Object(node));
        let next_depth = depth
            .checked_add(1)
            .ok_or_else(|| io::Error::other("depth overflow"))?;
        for child in handle.children.borrow().iter().rev() {
            pending.push((child.clone(), index, next_depth));
        }
    }
    let document = Document::rendered_dom(
        id,
        epoch.try_into()?,
        serde_json::to_vec(&json!({
            "schema":"yosoi.rendered-dom.v1", "document_epoch":epoch,"tree_model":"document_light_dom","root":1,"nodes":nodes
        }))?,
    )?;
    document.parse()?;
    Ok(document)
}
