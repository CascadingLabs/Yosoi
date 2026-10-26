//! Behavioral tests of the public Rust Surface index and cursor lifecycle.
use serde_json::json;
use std::{
    collections::BTreeSet,
    error::Error,
    fmt::Write as _,
    io,
    sync::{Arc, Barrier},
    thread,
};
use yosoi::{
    documents::{Document, DocumentEpoch},
    surface::{
        ActionStatus, Budget, EventKind, Limits, Reference, Session, SessionPolicy, Surface,
        SurfaceError,
    },
};

type TestResult = Result<(), Box<dyn Error>>;
fn index(html: &str) -> Result<Surface, Box<dyn Error>> {
    Ok(Surface::new(&Document::html(
        "fixture",
        html.as_bytes().to_vec(),
    )?)?)
}
fn first(index: &Surface, query: &str) -> Result<Reference, Box<dyn Error>> {
    index
        .find(query, None, Budget::default())?
        .entries
        .first()
        .map(|entry| entry.reference.clone())
        .ok_or_else(|| io::Error::other("missing fixture text").into())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn html_reduction_preserves_routing_and_interleaved_text() -> TestResult {
    let prepared = index(
        "<main><h1>Catalogue</h1><ul>\n<li><b>A</b> one</li>\n<li><b>B</b> two</li>\n<li><b>C</b> three</li>\n</ul><p>Unique prose λ🙂</p></main>",
    )?;
    let overview = prepared.overview(None, Budget::default())?;
    let region = overview
        .entries
        .iter()
        .find(|entry| entry.members == Some(3))
        .ok_or_else(|| io::Error::other("repeat region missing"))?;
    let members = prepared.expand(&region.reference, None, Budget::default())?;
    assert!(
        region
            .shape
            .as_deref()
            .is_some_and(|shape| shape.contains("li"))
    );
    assert!(region.exemplar.is_some());
    assert_eq!(members.total, 3);
    let last = members
        .entries
        .last()
        .ok_or_else(|| io::Error::other("missing member"))?;
    let detail = prepared.inspect(&last.reference, None, Budget::default())?;
    assert_eq!(detail.content, "<li><b>C</b> three</li>");
    let prose = first(&prepared, "Unique prose")?;
    assert!(
        prepared
            .inspect(&prose, None, Budget::default())?
            .content
            .contains("λ🙂")
    );
    let other = index("<main><p>Changed</p></main>")?;
    assert!(matches!(
        other.validate(&prose),
        Err(SurfaceError::WrongCapture)
    ));
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn xml_json_and_text_keep_native_evidence_and_boundaries() -> TestResult {
    assert!(
        Surface::new(&Document::json(
            "duplicate",
            br#"{"key":1,"key":2}"#.to_vec()
        )?)
        .is_err()
    );
    let xml = Surface::new(&Document::xml(
        "xml",
        b"<r xmlns:x='urn:x'><x:item key='a'> Exact </x:item></r>".to_vec(),
    )?)?;
    let reference = first(&xml, "Exact")?;
    assert_eq!(
        xml.inspect(&reference, None, Budget::default())?.content,
        " Exact "
    );
    let parent = xml
        .parent(&reference)?
        .ok_or_else(|| io::Error::other("XML parent missing"))?;
    assert!(
        xml.inspect(&parent, None, Budget::default())?
            .content
            .starts_with("<x:item")
    );
    assert!(Surface::new(&Document::xml("bad", b"<unclosed>".to_vec())?).is_err());
    let json_index = Surface::new(&Document::json(
        "json",
        br#"{"a/b":{"~key":"Exact"},"enabled":true,"count":7}"#.to_vec(),
    )?)?;
    let reference = first(&json_index, "Exact")?;
    assert_eq!(json_index.coordinate(&reference)?.value, "/a~1b/~0key");
    assert_eq!(
        json_index
            .inspect(&reference, None, Budget::default())?
            .content,
        "\"Exact\""
    );
    let text = "λ🙂 paragraph\n".repeat(400);
    let prepared = Surface::new(&Document::text("text", text.as_bytes().to_vec())?)?;
    let mut token = None;
    let mut recovered = String::new();
    loop {
        let detail = prepared.inspect(
            &prepared.root(),
            token.as_ref(),
            Budget {
                bytes: 700,
                items: 2,
            },
        )?;
        assert!(serde_json::to_vec(&detail)?.len() <= 700);
        recovered.push_str(&detail.content);
        if detail.next.is_none() {
            break;
        }
        assert!(
            detail
                .next
                .as_ref()
                .is_some_and(|next| next.offset() > detail.offset)
        );
        token = detail.next;
    }
    assert_eq!(recovered, text);
    assert!(
        prepared
            .inspect(
                &prepared.root(),
                None,
                Budget {
                    bytes: 16,
                    items: 1
                }
            )
            .is_err()
    );
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn continuations_bind_operation_query_and_scope() -> TestResult {
    let mut source = String::from("<ul>");
    for i in 0..25 {
        write!(source, "<li>item {i}</li>")?;
    }
    source.push_str("</ul>");
    let prepared = index(&source)?;
    let region = prepared
        .overview(None, Budget::default())?
        .entries
        .into_iter()
        .find(|e| e.members == Some(25))
        .ok_or_else(|| io::Error::other("region missing"))?;
    let mut token = None;
    let mut seen = BTreeSet::new();
    loop {
        let page = prepared.expand(
            &region.reference,
            token.as_ref(),
            Budget {
                bytes: 1000,
                items: 4,
            },
        )?;
        assert!(serde_json::to_vec(&page)?.len() <= 1000);
        for entry in page.entries {
            assert!(seen.insert(entry.reference.node));
        }
        if page.next.is_none() {
            break;
        }
        token = page.next;
    }
    assert_eq!(seen.len(), 25);
    let page = prepared.expand(
        &region.reference,
        None,
        Budget {
            bytes: 1000,
            items: 1,
        },
    )?;
    assert!(
        prepared
            .find("item", page.next.as_ref(), Budget::default())
            .is_err()
    );
    let page = prepared.find(
        "item",
        None,
        Budget {
            bytes: 1000,
            items: 1,
        },
    )?;
    assert!(
        prepared
            .find("different", page.next.as_ref(), Budget::default())
            .is_err()
    );
    Ok(())
}

fn dom(epoch: u64) -> Result<Document, Box<dyn Error>> {
    Ok(Document::rendered_dom(
        "dom",
        DocumentEpoch::try_from(epoch)?,
        serde_json::to_vec(
            &json!({"schema":"yosoi.rendered-dom.v1","document_epoch":epoch,"tree_model":"document_light_dom","root":1,"nodes":[
        {"kind":"document","id":1,"parent":null,"children":[2]},
        {"kind":"element","id":2,"parent":1,"children":[3],"namespace_uri":"http://www.w3.org/1999/xhtml","tag_name":"button","attributes":[{"namespace_uri":"","name":"type","value":"button"}]},
        {"kind":"text","id":3,"parent":2,"children":[],"value":"Submit"}]}),
        )?,
    )?)
}
fn ax(complete: bool) -> Result<Document, Box<dyn Error>> {
    Ok(Document::accessibility_tree(
        "ax",
        DocumentEpoch::try_from(7)?,
        serde_json::to_vec(
            &json!({"schema":"yosoi.accessibility-tree.v1","document_epoch":7,"root":"root","completeness":if complete{json!({"status":"complete"})}else{json!({"status":"unknown","reason_code":"provider_gap"})},"nodes":[
        {"id":"root","parent":null,"children":["button"],"ignored":false,"role":"RootWebArea","accessible_name":null,"text":null,"states":{}},
        {"id":"button","parent":"root","children":[],"ignored":false,"role":"button","accessible_name":"Submit","text":null,"states":{"focused":false}}]}),
        )?,
    )?)
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn native_snapshots_keep_epoch_identity_and_coverage() -> TestResult {
    let dom_one = Surface::new(&dom(7)?)?;
    let found = first(&dom_one, "Submit")?;
    assert_eq!(dom_one.coordinate(&found)?.kind, "dom_node");
    assert_eq!(dom_one.coordinate(&found)?.value, "3");
    assert!(Surface::new(&dom(8)?)?.validate(&found).is_err());
    let accessibility = Surface::new(&ax(false)?)?;
    assert!(!accessibility.coverage().complete);
    let session = Session::new(accessibility.clone(), SessionPolicy::default())?;
    let cursor = session.cursor()?;
    session.attach()?;
    cursor.focus(&first(&accessibility, "Submit")?)?;
    cursor.promote()?;
    assert!(matches!(
        cursor.begin_action(),
        Err(SurfaceError::Uncertain)
    ));
    let wrong =
        Document::rendered_dom("dom", DocumentEpoch::try_from(8)?, dom(7)?.bytes().to_vec())?;
    assert!(Surface::new(&wrong).is_err());
    assert!(Surface::new(&ax(true)?)?.coverage().complete);
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn native_attribute_namespaces_do_not_overwrite_each_other() -> TestResult {
    let payload = json!({"schema":"yosoi.rendered-dom.v1","document_epoch":1,"tree_model":"document_light_dom","root":1,"nodes":[
        {"kind":"document","id":1,"parent":null,"children":[2]},
        {"kind":"element","id":2,"parent":1,"children":[],"namespace_uri":"http://www.w3.org/2000/svg","tag_name":"a","attributes":[{"namespace_uri":"","name":"href","value":"plain-link"},{"namespace_uri":"http://www.w3.org/1999/xlink","name":"href","value":"namespaced-link"}]}
    ]});
    let prepared = Surface::new(&Document::rendered_dom(
        "namespaces",
        DocumentEpoch::try_from(1)?,
        serde_json::to_vec(&payload)?,
    )?)?;
    assert_eq!(
        prepared.find("plain-link", None, Budget::default())?.total,
        1
    );
    assert_eq!(
        prepared
            .find("namespaced-link", None, Budget::default())?
            .total,
        1
    );
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn independent_cursors_and_single_hot_owner_under_race() -> TestResult {
    let prepared = index("<main><p>Alpha</p><p>Beta</p></main>")?;
    let session = Session::new(
        prepared.clone(),
        SessionPolicy {
            cursors: 2,
            ..SessionPolicy::default()
        },
    )?;
    let one = session.cursor()?;
    let two = session.cursor()?;
    assert!(session.cursor().is_err());
    one.focus(&first(&prepared, "Alpha")?)?;
    two.focus(&first(&prepared, "Beta")?)?;
    assert_ne!(one.position()?.focus, two.position()?.focus);
    assert!(matches!(one.promote(), Err(SurfaceError::Detached)));
    session.attach()?;
    let barrier = Arc::new(Barrier::new(3));
    let readers = [one.clone(), two.clone()]
        .into_iter()
        .map(|cursor| {
            let barrier = barrier.clone();
            thread::spawn(move || {
                barrier.wait();
                cursor.promote().is_ok()
            })
        })
        .collect::<Vec<_>>();
    barrier.wait();
    let mut winners = 0usize;
    for reader in readers {
        if reader
            .join()
            .map_err(|_| io::Error::other("reader thread failed"))?
        {
            winners = winners.saturating_add(1);
        }
    }
    assert_eq!(winners, 1);
    let owner = session
        .hot_owner()?
        .ok_or_else(|| io::Error::other("no hot owner"))?;
    if one.id() == owner {
        one.cool()?;
        two.promote()?;
    } else {
        two.cool()?;
        one.promote()?;
    }
    let shared = Arc::new(prepared);
    let tasks = (0..2)
        .map(|_| {
            let shared = shared.clone();
            thread::spawn(move || {
                shared
                    .find("Alpha", None, Budget::default())
                    .map(|page| page.entries.len())
            })
        })
        .collect::<Vec<_>>();
    for task in tasks {
        assert_eq!(
            task.join().map_err(|_| io::Error::other("read failed"))??,
            1
        );
    }
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn watches_reconcile_explicitly_without_moving_focus() -> TestResult {
    let before = index("<main><p>Product stable</p><p>Cart zero</p></main>")?;
    let session = Session::new(
        before.clone(),
        SessionPolicy {
            cursors: 2,
            ..SessionPolicy::default()
        },
    )?;
    let product = session.cursor()?;
    let cart = session.cursor()?;
    session.attach()?;
    let old_product = first(&before, "Product stable")?;
    let old_cart = first(&before, "Cart zero")?;
    product.focus(&old_product)?;
    let product_watch = product.subscribe(&old_product)?;
    let cart_watch = cart.subscribe(&old_cart)?;
    let after = index("<main><p>Product stable</p><p>Cart one</p></main>")?;
    session.publish(after.clone())?;
    assert_eq!(product.position()?.focus, Some(old_product.clone()));
    assert!(
        product
            .inspect(&old_product, None, Budget::default())?
            .content
            .contains("Product stable")
    );
    assert_eq!(
        product.reconcile(product_watch, &first(&after, "Product stable")?)?,
        EventKind::Unchanged
    );
    assert_eq!(
        cart.reconcile(cart_watch, &first(&after, "Cart one")?)?,
        EventKind::Changed
    );
    assert!(
        product
            .events()?
            .events
            .iter()
            .any(|event| event.kind == EventKind::Unchanged)
    );
    assert!(
        cart.events()?
            .events
            .iter()
            .any(|event| event.kind == EventKind::Changed)
    );
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn leases_preserve_dispatch_and_revoke_on_new_evidence() -> TestResult {
    let before = index("<button>Add</button>")?;
    let session = Session::new(before.clone(), SessionPolicy::default())?;
    let cursor = session.cursor()?;
    session.attach()?;
    cursor.focus(&first(&before, "Add")?)?;
    cursor.promote()?;
    let lease = cursor.begin_action()?;
    assert!(matches!(cursor.cool(), Err(SurfaceError::ActionInFlight)));
    let after = index("<button disabled>Add</button>")?;
    session.publish(after.clone())?;
    assert!(matches!(lease.revalidate(), Err(SurfaceError::Stale)));
    drop(lease);
    cursor.focus(&first(&after, "Add")?)?;
    let mut lease = cursor.begin_action()?;
    lease.mark_dispatched()?;
    let receipt = lease.finish(ActionStatus::Unconfirmed, "post-action capture unavailable")?;
    assert!(receipt.dispatched);
    assert_eq!(receipt.status, ActionStatus::Unconfirmed);
    let mut lease = cursor.begin_action()?;
    lease.mark_dispatched()?;
    assert!(
        lease
            .finish(ActionStatus::Rejected, "cannot erase a dispatch")
            .is_err()
    );
    assert!(
        cursor
            .events()?
            .events
            .iter()
            .any(|e| e.note.contains("outcome unconfirmed"))
    );
    let lease = cursor.begin_action()?;
    session.detach()?;
    assert!(matches!(lease.revalidate(), Err(SurfaceError::Detached)));
    drop(lease);
    assert_eq!(session.hot_owner()?, None);
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn moving_focus_does_not_retarget_an_outstanding_action_lease() -> TestResult {
    let prepared = index("<button>First action</button><button>Second action</button>")?;
    let session = Session::new(prepared.clone(), SessionPolicy::default())?;
    let cursor = session.cursor()?;
    session.attach()?;
    cursor.focus(&first(&prepared, "First action")?)?;
    cursor.promote()?;
    let lease = cursor.begin_action()?;
    cursor.focus(&first(&prepared, "Second action")?)?;
    assert!(matches!(lease.revalidate(), Err(SurfaceError::Stale)));
    let receipt = lease.finish(ActionStatus::Rejected, "focus changed before dispatch")?;
    assert!(!receipt.dispatched);
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn history_loss_and_preparation_limits_are_explicit() -> TestResult {
    let initial = index("<p>zero</p>")?;
    let session = Session::new(
        initial,
        SessionPolicy {
            events: 2,
            captures: 1,
            ..SessionPolicy::default()
        },
    )?;
    let cursor = session.cursor()?;
    session.attach()?;
    for text in ["one", "two", "three"] {
        session.publish(index(&format!("<p>{text}</p>"))?)?;
    }
    assert!(cursor.events()?.lost);
    let input = Document::html("limits", b"<main><p>Nested</p></main>".to_vec())?;
    assert!(
        Surface::with_limits(
            &input,
            Limits {
                nodes: 2,
                ..Limits::default()
            }
        )
        .is_err()
    );
    assert!(
        Surface::with_limits(
            &input,
            Limits {
                input_bytes: 2,
                ..Limits::default()
            }
        )
        .is_err()
    );
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn invalidation_blocks_actions_before_replacement_capture_arrives() -> TestResult {
    use yosoi::surface::Freshness;
    let prepared = index("<button>Add</button>")?;
    let session = Session::new(prepared.clone(), SessionPolicy::default())?;
    let cursor = session.cursor()?;
    session.attach()?;
    cursor.focus(&first(&prepared, "Add")?)?;
    cursor.promote()?;
    let watch = cursor.subscribe(&prepared.root())?;
    let lease = cursor.begin_action()?;
    session.invalidate("mutation observed; capture pending")?;
    assert!(matches!(
        cursor.reconcile(watch, &prepared.root()),
        Err(SurfaceError::Uncertain)
    ));
    assert_eq!(cursor.status()?.focus_freshness, Freshness::Unknown);
    assert!(matches!(lease.revalidate(), Err(SurfaceError::Uncertain)));
    drop(lease);
    assert!(matches!(
        cursor.begin_action(),
        Err(SurfaceError::Uncertain)
    ));
    session.publish(prepared)?;
    assert_eq!(cursor.status()?.focus_freshness, Freshness::Current);
    let lease = cursor.begin_action()?;
    lease.finish(ActionStatus::Rejected, "provider rejected before effect")?;
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn html_templates_and_comments_remain_recoverable_without_live_ordinals() -> TestResult {
    let prepared = index(
        "<!doctype html><main><!--audit-marker--><template><button>Hidden prototype</button></template><button>Visible action</button></main>",
    )?;
    let hidden = first(&prepared, "Hidden prototype")?;
    let parent = prepared
        .parent(&hidden)?
        .ok_or_else(|| io::Error::other("template element missing"))?;
    assert_eq!(prepared.coordinate(&parent)?.kind, "html_template_element");
    let visible = first(&prepared, "Visible action")?;
    let parent = prepared
        .parent(&visible)?
        .ok_or_else(|| io::Error::other("visible element missing"))?;
    assert_eq!(prepared.coordinate(&parent)?.kind, "html_element");
    let detail = prepared.inspect(
        &prepared.root(),
        None,
        Budget {
            bytes: 8192,
            items: 20,
        },
    )?;
    assert!(
        detail
            .content
            .contains("<template><button>Hidden prototype</button></template>")
    );
    assert!(detail.content.contains("<!--audit-marker-->"));
    let routing = index(
        "<head><style>STYLE-NOISE</style><script>CODE-NOISE</script></head><body><h1>Useful title</h1></body>",
    )?;
    let overview = routing.overview(None, Budget::default())?;
    let preview = &overview
        .entries
        .first()
        .ok_or_else(|| io::Error::other("root absent"))?
        .preview;
    assert!(!preview.contains("NOISE"));
    assert!(preview.contains("Useful title"));
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn native_region_comparison_includes_descendant_values() -> TestResult {
    let source = dom(7)?;
    let before = Surface::new(&source)?;
    let changed = String::from_utf8(source.bytes().to_vec())?.replace("Submit", "Continue");
    let after = Surface::new(&Document::rendered_dom(
        "dom",
        DocumentEpoch::try_from(7)?,
        changed.into_bytes(),
    )?)?;
    let session = Session::new(before.clone(), SessionPolicy::default())?;
    let cursor = session.cursor()?;
    session.attach()?;
    let watch = cursor.subscribe(&before.root())?;
    session.publish(after.clone())?;
    assert_eq!(cursor.reconcile(watch, &after.root())?, EventKind::Changed);
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn accessibility_previews_do_not_repeat_names_through_descendants() -> TestResult {
    let payload = json!({"schema":"yosoi.accessibility-tree.v1","document_epoch":1,"root":"root","completeness":{"status":"complete"},"nodes":[
        {"id":"root","parent":null,"children":["button"],"ignored":false,"role":"RootWebArea","accessible_name":null,"text":null,"states":{}},
        {"id":"button","parent":"root","children":["text"],"ignored":false,"role":"button","accessible_name":"Submit","text":null,"states":{}},
        {"id":"text","parent":"button","children":[],"ignored":false,"role":"StaticText","accessible_name":"Submit","text":"Submit","states":{}}
    ]});
    let prepared = Surface::new(&Document::accessibility_tree(
        "ax-preview",
        DocumentEpoch::try_from(1)?,
        serde_json::to_vec(&payload)?,
    )?)?;
    let matches = prepared.find("Submit", None, Budget::default())?;
    assert_eq!(matches.total, 2);
    assert!(
        matches
            .entries
            .iter()
            .all(|entry| entry.preview == "Submit")
    );
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn combined_observation_keeps_source_provenance_and_independent_views() -> TestResult {
    let text = index("<p>Needle lamp</p>")?;
    let json = Surface::new(&Document::json(
        "json",
        br#"{"name":"Needle lamp"}"#.to_vec(),
    )?)?;
    let combined = Surface::combine(
        "one page, sequential captures",
        vec![("document".into(), text.clone()), ("data".into(), json)],
        Limits::default(),
    )?;
    let views = combined.expand(&combined.root(), None, Budget::default())?;
    assert_eq!(views.total, 2);
    let matches = combined.find("Needle lamp", None, Budget::default())?;
    assert_eq!(matches.total, 2);
    for entry in matches.entries {
        assert!(entry.view.is_some());
        let source = combined
            .source_reference(&entry.reference)?
            .ok_or_else(|| io::Error::other("source provenance missing"))?;
        assert!(
            combined
                .inspect(&entry.reference, None, Budget::default())?
                .content
                .contains("Needle lamp")
        );
        assert_eq!(
            combined.project(&source.view, &source.reference)?,
            entry.reference
        );
        if source.view == "document" {
            text.validate(&source.reference)?;
        }
    }
    assert!(
        combined
            .inspect(&combined.root(), None, Budget::default())?
            .content
            .contains("\"atomic\":false")
    );
    assert!(
        Surface::combine(
            "nested",
            vec![("nested".into(), combined)],
            Limits::default()
        )
        .is_err()
    );
    assert!(
        Surface::combine(
            "duplicate",
            vec![("same".into(), text.clone()), ("same".into(), text)],
            Limits::default()
        )
        .is_err()
    );
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn combined_identity_is_unambiguous_across_scope_and_view_boundaries() -> TestResult {
    let first = index("<p>first</p>")?;
    let second = index("<p>second</p>")?;
    let ordinary = Surface::combine(
        "scope",
        vec![("a".into(), first.clone()), ("b".into(), second.clone())],
        Limits::default(),
    )?;
    // This scope would collide with a raw concatenation of scope/name-length/name/source IDs.
    let boundary = String::from_utf8(1usize.to_le_bytes().to_vec())?;
    let deceptive_scope = format!("scope{boundary}a{}", first.identity());
    let different = Surface::combine(
        &deceptive_scope,
        vec![("b".into(), second)],
        Limits::default(),
    )?;
    assert_ne!(ordinary.identity(), different.identity());
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn location_only_changes_stale_the_observation_without_changing_document_evidence() -> TestResult {
    let document = index("<button>Continue</button>")?;
    let before_location = Surface::new(&Document::json(
        "location",
        br#"{"url":"https://example.invalid/one"}"#.to_vec(),
    )?)?;
    let after_location = Surface::new(&Document::json(
        "location",
        br#"{"url":"https://example.invalid/two"}"#.to_vec(),
    )?)?;
    let original = first(&document, "Continue")?;
    let before = Surface::combine(
        "page",
        vec![
            ("document".into(), document.clone()),
            ("location".into(), before_location.clone()),
        ],
        Limits::default(),
    )?;
    let after = Surface::combine(
        "page",
        vec![
            ("document".into(), document),
            ("location".into(), after_location.clone()),
        ],
        Limits::default(),
    )?;
    let session = Session::new(before.clone(), SessionPolicy::default())?;
    let cursor = session.cursor()?;
    session.attach()?;
    let old_document = before.project("document", &original)?;
    cursor.focus(&old_document)?;
    cursor.promote()?;
    let document_watch = cursor.subscribe(&old_document)?;
    let location_watch = cursor.subscribe(&before.project("location", &before_location.root())?)?;
    session.publish(after.clone())?;
    assert!(matches!(cursor.begin_action(), Err(SurfaceError::Stale)));
    assert_eq!(
        cursor.reconcile(document_watch, &after.project("document", &original)?)?,
        EventKind::Unchanged
    );
    assert_eq!(
        cursor.reconcile(
            location_watch,
            &after.project("location", &after_location.root())?
        )?,
        EventKind::Changed
    );
    Ok(())
}

#[cfg(feature = "surface-images")]
#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail the test; Result propagates fixture setup and SDK errors."
)]
fn image_zoom_returns_real_pixels_and_policy_bound_references() -> TestResult {
    use std::io::Cursor;
    let pixels = image::RgbaImage::from_fn(256, 128, |x, y| {
        if x < 128 && y < 64 {
            image::Rgba([255, 0, 0, 255])
        } else {
            image::Rgba([0, 0, 255, 255])
        }
    });
    let mut output = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgba8(pixels).write_to(&mut output, image::ImageFormat::Png)?;
    let bytes = output.into_inner();
    let prepared = Surface::from_image(&bytes, 64, Limits::default())?;
    let mixed = Surface::combine(
        "text plus raster",
        vec![
            ("document".into(), index("<p>Image description</p>")?),
            ("screenshot".into(), prepared.clone()),
        ],
        Limits::default(),
    )?;
    let image_view = mixed
        .expand(&mixed.root(), None, Budget::default())?
        .entries
        .into_iter()
        .find(|entry| entry.label == "screenshot")
        .ok_or_else(|| io::Error::other("image view missing"))?;
    let mixed_pixels = mixed.crop(&image_view.reference, 100_000)?;
    assert_eq!(mixed_pixels.rect.width, 256);
    assert_eq!(mixed_pixels.reference.capture, mixed.identity());
    let children = prepared.expand(&prepared.root(), None, Budget::default())?;
    assert_eq!(children.total, 4);
    let top_left = children
        .entries
        .first()
        .ok_or_else(|| io::Error::other("image tile missing"))?;
    let crop = prepared.crop(&top_left.reference, 100_000)?;
    let decoded = image::load_from_memory(&crop.png)?.to_rgba8();
    assert_eq!(decoded.width(), 128);
    assert_eq!(decoded.height(), 64);
    assert_eq!(decoded.get_pixel(0, 0).0, [255, 0, 0, 255]);
    assert!(prepared.crop(&top_left.reference, 1).is_err());
    assert!(
        Surface::from_image(&bytes, 128, Limits::default())?
            .validate(&top_left.reference)
            .is_err()
    );
    assert!(Surface::from_image(b"not an image", 64, Limits::default()).is_err());
    let mut jpeg = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgb8(image::RgbImage::from_pixel(
        32,
        16,
        image::Rgb([10, 80, 190]),
    ))
    .write_to(&mut jpeg, image::ImageFormat::Jpeg)?;
    let jpeg_index = Surface::from_image(&jpeg.into_inner(), 64, Limits::default())?;
    let jpeg_crop = jpeg_index.crop(&jpeg_index.root(), 100_000)?;
    let jpeg_pixels = image::load_from_memory(&jpeg_crop.png)?.to_rgb8();
    assert_eq!(jpeg_pixels.dimensions(), (32, 16));
    assert!(jpeg_pixels.get_pixel(0, 0).0.get(2) > jpeg_pixels.get_pixel(0, 0).0.first());
    let mut too_wide = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgb8(image::RgbImage::new(8193, 1))
        .write_to(&mut too_wide, image::ImageFormat::Png)?;
    assert!(Surface::from_image(&too_wide.into_inner(), 64, Limits::default()).is_err());
    let mut blue = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgba8(image::RgbaImage::from_pixel(
        256,
        128,
        image::Rgba([0, 0, 255, 255]),
    ))
    .write_to(&mut blue, image::ImageFormat::Png)?;
    let changed = Surface::from_image(&blue.into_inner(), 64, Limits::default())?;
    let session = Session::new(prepared.clone(), SessionPolicy::default())?;
    let cursor = session.cursor()?;
    session.attach()?;
    let watch = cursor.subscribe(&prepared.root())?;
    session.publish(changed.clone())?;
    assert_eq!(
        cursor.reconcile(watch, &changed.root())?,
        EventKind::Changed
    );
    Ok(())
}
