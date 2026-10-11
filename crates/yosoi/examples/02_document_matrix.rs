use std::error::Error;

use yosoi::prelude as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let xml = ys::Document::xml(
        "catalog.xml",
        b"<catalog><price currency='USD'>12</price></catalog>".to_vec(),
    )?;
    let xml_plan = ys::Plan::new([ys::output("prices", ys::xpath("/catalog/price")?.text())?])?;
    let _xml_outcome = xml.locate(&xml_plan);

    let json = ys::Document::json("product.json", br#"{"currency":"USD"}"#.to_vec())?;
    let json_plan = ys::Plan::new([ys::output(
        "currency",
        ys::json_pointer("/currency")?.value(),
    )?])?;
    let _json_outcome = json.locate(&json_plan);

    let text = ys::Document::text("orders.txt", b"Order #123".to_vec())?;
    let text_plan = ys::Plan::new([ys::output("orders", ys::regex(r"Order\s+#\d+")?.text())?])?;
    let _text_outcome = text.locate(&text_plan);

    let epoch = ys::DocumentEpoch::try_from(1)?;
    let dom = ys::Document::rendered_dom(
        "rendered-dom.json",
        epoch,
        br#"{
            "schema":"yosoi.rendered-dom.v1",
            "document_epoch":1,
            "tree_model":"document_light_dom",
            "root":1,
            "nodes":[
                {"kind":"document","id":1,"parent":null,"children":[2]},
                {"kind":"element","id":2,"parent":1,"children":[3],"namespace_uri":"http://www.w3.org/1999/xhtml","tag_name":"html","attributes":[]},
                {"kind":"element","id":3,"parent":2,"children":[4],"namespace_uri":"http://www.w3.org/1999/xhtml","tag_name":"body","attributes":[]},
                {"kind":"element","id":4,"parent":3,"children":[5],"namespace_uri":"http://www.w3.org/1999/xhtml","tag_name":"button","attributes":[{"namespace_uri":"","name":"class","value":"buy-now"}]},
                {"kind":"text","id":5,"parent":4,"children":[],"value":"Buy now"}
            ]
        }"#
        .to_vec(),
    )?;
    let dom_plan = ys::Plan::new([ys::output("buttons", ys::css("button.buy-now")?.text())?])?;
    let _dom_outcome = dom.locate(&dom_plan);

    let ax = ys::Document::accessibility_tree(
        "accessibility.json",
        epoch,
        br#"{
            "schema":"yosoi.accessibility-tree.v1",
            "document_epoch":1,
            "root":"button-1",
            "completeness":{"status":"complete"},
            "nodes":[{
                "id":"button-1",
                "parent":null,
                "children":[],
                "ignored":false,
                "role":"button",
                "accessible_name":"Buy now",
                "text":"Buy now",
                "states":{}
            }]
        }"#
        .to_vec(),
    )?;
    let ax_plan = ys::Plan::new([ys::output("buttons", ys::role("button")?.name())?])?;
    let _ax_outcome = ax.locate(&ax_plan);

    Ok(())
}
