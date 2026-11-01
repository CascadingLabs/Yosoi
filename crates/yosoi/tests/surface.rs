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
        ActionStatus, Budget, EventKind, ImageSurface, Limits, PixelCoordinateKind, PixelLimits,
        PixelOperation, PixelOrientation, PixelRect, Reference, Session, SessionPolicy, Surface,
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
    let decoded = image::load_from_memory(crop.png())?.to_rgba8();
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
    let jpeg_pixels = image::load_from_memory(jpeg_crop.png())?.to_rgb8();
    assert_eq!(jpeg_pixels.dimensions(), (32, 16));
    assert!(jpeg_pixels.get_pixel(0, 0).0.get(2) > jpeg_pixels.get_pixel(0, 0).0.first());
    let mut too_wide = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgb8(image::RgbImage::new(8193, 1))
        .write_to(&mut too_wide, image::ImageFormat::Png)?;
    assert!(Surface::from_image(&too_wide.into_inner(), 64, Limits::default()).is_err());
    let mut too_tall = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgb8(image::RgbImage::new(1, 8193))
        .write_to(&mut too_tall, image::ImageFormat::Png)?;
    assert!(Surface::from_image(&too_tall.into_inner(), 64, Limits::default()).is_err());
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

#[cfg(feature = "surface-images")]
#[test]
fn typed_image_direct_overview_and_crop_preserve_root_coordinates() -> TestResult {
    use std::io::Cursor;
    use yosoi::documents::ImageDocument;
    use yosoi::surface::{
        PixelArtifact,
        model::{ReadOperation, ReadRequest, ReadResult, SurfaceRead},
    };

    let pixels = image::RgbaImage::from_fn(256, 128, |x, y| {
        if x < 128 && y < 64 {
            image::Rgba([255, 0, 0, 255])
        } else {
            image::Rgba([0, 0, 255, 255])
        }
    });
    let mut encoded = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgba8(pixels).write_to(&mut encoded, image::ImageFormat::Png)?;
    let bytes = encoded.into_inner();
    let document = ImageDocument::from_bytes("typed-raster", bytes.clone())?;
    let surface = ImageSurface::from_image_document(
        &document,
        64,
        Limits::default(),
        PixelLimits::default(),
    )?;
    assert!(!surface.descriptor().controllable);
    assert!(
        surface
            .descriptor()
            .capabilities
            .iter()
            .any(|capability| capability.id == "image.direct@1")
    );
    let page = surface.read(&ReadRequest {
        operation: ReadOperation::Overview,
        budget: Budget::default(),
        continuation: None,
    })?;
    assert!(matches!(page, ReadResult::Page(_)));

    let direct = surface.direct_image()?;
    assert_eq!(direct.bytes(), bytes);
    assert_eq!(
        direct.info().coordinate_space.kind,
        PixelCoordinateKind::OriginalRaster
    );
    assert_eq!(
        direct.info().coordinate_space.orientation,
        PixelOrientation::ExifUnapplied
    );

    let overview = surface.overview_image(64)?;
    assert_eq!((overview.info().width, overview.info().height), (64, 32));
    assert!(matches!(
        &overview.info().transform.operation,
        PixelOperation::Overview { max_side: 64, .. }
    ));
    let overview_region = PixelRect {
        x: 0,
        y: 0,
        width: 32,
        height: 16,
    };
    let original_region = overview.map_rect_to_source(overview_region)?;
    assert_eq!(
        original_region,
        PixelRect {
            x: 0,
            y: 0,
            width: 128,
            height: 64,
        }
    );
    let crop = surface.crop_rect(original_region, 100_000)?;
    let decoded = image::load_from_memory(crop.png())?.to_rgba8();
    assert_eq!(decoded.dimensions(), (128, 64));
    assert_eq!(decoded.get_pixel(0, 0).0, [255, 0, 0, 255]);
    assert_eq!(
        crop.artifact.info().transform.parent_identity.as_deref(),
        Some(direct.info().identity.as_str())
    );
    assert!(
        PixelArtifact::crop_from(
            &crop.artifact,
            ImageDocument::from_bytes("nested-crop", crop.png().to_vec())?,
            PixelRect {
                x: 0,
                y: 0,
                width: 8,
                height: 8,
            },
        )
        .is_err()
    );
    assert!(
        surface
            .crop_rect(
                PixelRect {
                    x: 255,
                    y: 0,
                    width: 2,
                    height: 2,
                },
                100_000,
            )
            .is_err()
    );
    assert!(
        surface
            .crop_rect(
                PixelRect {
                    x: 0,
                    y: 0,
                    width: 0,
                    height: 4,
                },
                100_000,
            )
            .is_err()
    );

    let source_limited = Limits {
        input_bytes: bytes.len().saturating_sub(1),
        ..Limits::default()
    };
    assert!(
        ImageSurface::from_image_document(&document, 64, source_limited, PixelLimits::default(),)
            .is_err()
    );
    let decode_limited = PixelLimits {
        max_decoded_bytes: 131_071,
        ..PixelLimits::default()
    };
    assert!(
        ImageSurface::from_image_document(&document, 64, Limits::default(), decode_limited,)
            .is_err()
    );
    let output_limited = PixelLimits {
        max_output_pixels: 2_047,
        ..PixelLimits::default()
    };
    let bounded_output =
        ImageSurface::from_image_document(&document, 64, Limits::default(), output_limited)?;
    assert!(bounded_output.overview_image(64).is_err());
    let byte_limited = PixelLimits {
        max_output_bytes: 1,
        ..PixelLimits::default()
    };
    let bounded_bytes =
        ImageSurface::from_image_document(&document, 64, Limits::default(), byte_limited)?;
    assert!(bounded_bytes.direct_image().is_err());

    let differently_tiled = ImageSurface::from_image_document(
        &document,
        128,
        Limits::default(),
        PixelLimits::default(),
    )?;
    let second_direct = differently_tiled.direct_image()?;
    assert_ne!(
        surface.index().identity(),
        differently_tiled.index().identity()
    );
    assert_eq!(direct.source_identity()?, second_direct.source_identity()?);
    assert_eq!(direct.info().identity, second_direct.info().identity);
    Ok(())
}

#[cfg(feature = "surface-images")]
#[test]
fn small_image_compares_direct_overview_and_crop_delivery() -> TestResult {
    use std::{io::Cursor, time::Instant};
    use yosoi::documents::ImageDocument;
    use yosoi::surface::PixelArtifact;

    let background = image::Rgba([22, 28, 36, 255]);
    let ink = image::Rgba([245, 232, 180, 255]);
    let glyph = [
        (7, 2),
        (6, 3),
        (8, 3),
        (5, 4),
        (9, 4),
        (4, 5),
        (10, 5),
        (3, 6),
        (11, 6),
        (2, 7),
        (12, 7),
        (7, 8),
        (6, 9),
        (8, 9),
        (5, 10),
        (9, 10),
        (4, 11),
        (10, 11),
        (3, 12),
        (11, 12),
    ];
    let original = image::RgbaImage::from_fn(16, 16, |x, y| {
        if glyph.contains(&(x, y)) {
            ink
        } else {
            background
        }
    });
    let mut encoded = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgba8(original.clone())
        .write_to(&mut encoded, image::ImageFormat::Png)?;
    let source_bytes = encoded.into_inner();
    let document = ImageDocument::from_bytes("small-pixel-label", source_bytes.clone())?;

    let started = Instant::now();
    let direct = PixelArtifact::decode_image_document(document.clone(), PixelLimits::default())?;
    let direct_ms = started.elapsed().as_millis();
    let started = Instant::now();
    let surface = ImageSurface::from_image_document(
        &document,
        32,
        Limits::default(),
        PixelLimits::default(),
    )?;
    let index_ms = started.elapsed().as_millis();
    let started = Instant::now();
    let overview = surface.overview_image(8)?;
    let overview_ms = started.elapsed().as_millis();
    let overview_pixels = image::load_from_memory(overview.bytes())?.to_rgba8();
    assert!(overview_pixels.pixels().all(|pixel| pixel.0 != ink.0));

    let source_rect = overview.map_rect_to_source(PixelRect {
        x: 1,
        y: 1,
        width: 6,
        height: 6,
    })?;
    let started = Instant::now();
    let crop = surface.crop_rect(source_rect, PixelLimits::default().max_output_bytes)?;
    let crop_ms = started.elapsed().as_millis();
    let crop_pixels = image::load_from_memory(crop.png())?.to_rgba8();
    for y in 0..source_rect.height {
        for x in 0..source_rect.width {
            assert_eq!(
                crop_pixels.get_pixel(x, y),
                original.get_pixel(source_rect.x + x, source_rect.y + y)
            );
        }
    }
    assert_eq!(direct.bytes(), source_bytes);
    assert_eq!(
        image::load_from_memory(direct.bytes())?
            .to_rgba8()
            .get_pixel(7, 8),
        &ink
    );
    let overview_plus_crop_bytes = overview
        .bytes()
        .len()
        .checked_add(crop.png().len())
        .ok_or("small fixture byte total overflow")?;
    let overview_plus_crop_pixels = u64::from(overview.info().width)
        .checked_mul(u64::from(overview.info().height))
        .and_then(|overview_count| {
            u64::from(crop.artifact.info().width)
                .checked_mul(u64::from(crop.artifact.info().height))
                .and_then(|crop_count| overview_count.checked_add(crop_count))
        })
        .ok_or("small fixture pixel total overflow")?;
    let overview_crop_ms = index_ms
        .checked_add(overview_ms)
        .and_then(|elapsed| elapsed.checked_add(crop_ms))
        .ok_or("small fixture processing time overflow")?;
    println!(
        "small image: direct={} bytes/{} pixels/{direct_ms} ms; overview={} bytes/{} pixels/{overview_ms} ms; overview+crop={overview_plus_crop_bytes} bytes/{} pixels/{overview_crop_ms} ms including index preparation; the pixel-encoded λ glyph is exact in direct pixels and recovered exactly by the crop",
        direct.bytes().len(),
        direct.info().width * direct.info().height,
        overview.bytes().len(),
        overview.info().width * overview.info().height,
        overview_plus_crop_pixels,
    );
    Ok(())
}

#[cfg(feature = "surface-images")]
#[test]
fn dense_image_overview_and_crop_report_measured_pixel_tradeoffs() -> TestResult {
    use std::{io::Cursor, time::Instant};
    use yosoi::documents::ImageDocument;
    use yosoi::surface::{PixelArtifact, PixelLimits};

    let pixels = image::RgbaImage::from_fn(1920, 1080, |x, y| {
        if (1500..1502).contains(&x) && (702..704).contains(&y) {
            image::Rgba([255, 0, 0, 255])
        } else {
            image::Rgba([24, 32, 40, 255])
        }
    });
    let mut encoded = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgba8(pixels).write_to(&mut encoded, image::ImageFormat::Png)?;
    let source_bytes = encoded.into_inner();
    let source = ImageDocument::from_bytes("dense-dashboard", source_bytes.clone())?;
    let started = std::time::Instant::now();
    let direct = PixelArtifact::decode_image_document(source.clone(), PixelLimits::default())?;
    let direct_ms = started.elapsed().as_millis();
    let started = Instant::now();
    let surface =
        ImageSurface::from_image_document(&source, 256, Limits::default(), PixelLimits::default())?;
    let index_ms = started.elapsed().as_millis();
    let started = Instant::now();
    let overview = surface.overview_image(320)?;
    let overview_ms = started.elapsed().as_millis();
    let overview_marker = image::load_from_memory(overview.bytes())?.to_rgba8();
    assert_ne!(overview_marker.get_pixel(250, 117).0, [255, 0, 0, 255]);

    let started = Instant::now();
    let source_region = overview.map_rect_to_source(PixelRect {
        x: 249,
        y: 116,
        width: 3,
        height: 3,
    })?;
    let crop = surface.crop_rect(source_region, 100_000)?;
    let crop_ms = started.elapsed().as_millis();
    let crop_pixels = image::load_from_memory(crop.png())?.to_rgba8();
    assert_eq!(crop_pixels.get_pixel(6, 6).0, [255, 0, 0, 255]);

    let overview_plus_crop_bytes = overview
        .bytes()
        .len()
        .checked_add(crop.png().len())
        .ok_or("dense fixture byte total overflow")?;
    let overview_plus_crop_pixels = u64::from(overview.info().width)
        .checked_mul(u64::from(overview.info().height))
        .and_then(|overview_count| {
            u64::from(crop.artifact.info().width)
                .checked_mul(u64::from(crop.artifact.info().height))
                .and_then(|crop_count| overview_count.checked_add(crop_count))
        })
        .ok_or("dense fixture pixel total overflow")?;
    let overview_crop_ms = index_ms
        .checked_add(overview_ms)
        .and_then(|elapsed| elapsed.checked_add(crop_ms))
        .ok_or("dense fixture processing time overflow")?;

    println!(
        "dense image: direct={} bytes/{} pixels/{direct_ms} ms; index={index_ms} ms; overview={} bytes/{} pixels/{overview_ms} ms; overview+crop={} bytes/{} pixels/{overview_crop_ms} ms including index preparation; the 2x2 red marker is not a full red overview pixel and is exact in the crop",
        direct.bytes().len(),
        direct.info().width * direct.info().height,
        overview.bytes().len(),
        overview.info().width * overview.info().height,
        overview_plus_crop_bytes,
        overview_plus_crop_pixels,
    );
    assert_eq!(direct.bytes(), source_bytes);
    Ok(())
}

#[cfg(feature = "surface-images")]
#[tokio::test]
async fn archived_pixel_artifact_restores_typed_pixels_and_provenance() -> TestResult {
    use std::io::Cursor;
    use yosoi::surface::PixelArtifact;
    use yosoi::{Archive, documents::ImageDocument};

    let pixels = image::RgbaImage::from_pixel(32, 16, image::Rgba([30, 120, 210, 255]));
    let mut encoded = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgba8(pixels).write_to(&mut encoded, image::ImageFormat::Png)?;
    let document = ImageDocument::from_bytes("archive-raster", encoded.into_inner())?;
    let surface = Surface::from_image_document(&document, 64, Limits::default())?;
    let crop = surface.crop_image(
        PixelRect {
            x: 4,
            y: 3,
            width: 12,
            height: 8,
        },
        100_000,
    )?;
    let temporary = tempfile::tempdir()?;
    let archive = Archive::open(temporary.path()).await?;
    let reference = crop.artifact.write_to(&archive).await?;
    drop(archive);

    let reopened = Archive::open(temporary.path()).await?;
    let restored = PixelArtifact::read_from(&reopened, &reference).await?;
    assert_eq!(restored, crop.artifact);
    assert_eq!(
        restored.info().transform.operation,
        crop.artifact.info().transform.operation
    );
    assert_eq!(restored.bytes(), crop.png());
    Ok(())
}

#[cfg(feature = "surface-images")]
#[tokio::test]
async fn archived_legacy_text_image_envelope_restores_exact_pixels() -> TestResult {
    use std::io::Cursor;
    use yosoi::Archive;
    use yosoi::surface::{ArchiveLimits, ArchivedSource, Outcome, SourceInterpretation};

    let pixels = image::RgbaImage::from_fn(16, 8, |x, y| {
        if x < 8 && y < 4 {
            image::Rgba([255, 80, 20, 255])
        } else {
            image::Rgba([18, 36, 220, 255])
        }
    });
    let mut encoded = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgba8(pixels).write_to(&mut encoded, image::ImageFormat::Png)?;
    let bytes = encoded.into_inner();
    let surface = Surface::from_image(&bytes, 32, Limits::default())?;
    let legacy_source = ArchivedSource::capture("legacy-image", &surface)?;
    assert!(matches!(
        legacy_source.interpretation,
        SourceInterpretation::Image { tile_side: 32 }
    ));
    assert_eq!(
        legacy_source.profile,
        Some(yosoi::documents::DocumentProfile::source_text())
    );

    let temporary = tempfile::tempdir()?;
    let archive = Archive::open(temporary.path()).await?;
    let outcome = Outcome::new("legacy-image-outcome", ArchiveLimits::default())?
        .with_source(legacy_source)?;
    let reference = archive.write(&outcome).await?;
    let restored = archive.read(&reference).await?;
    let reopened = restored.surface("legacy-image", Limits::default())?;
    let crop = reopened.crop(&reopened.root(), 100_000)?;
    let decoded = image::load_from_memory(crop.png())?.to_rgba8();
    assert_eq!(decoded.dimensions(), (16, 8));
    assert_eq!(decoded.get_pixel(0, 0).0, [255, 80, 20, 255]);
    assert_eq!(decoded.get_pixel(15, 7).0, [18, 36, 220, 255]);
    Ok(())
}

#[cfg(feature = "surface-images")]
#[test]
fn pixel_artifact_rejects_corrupt_encoded_pixels_with_valid_header() -> TestResult {
    use std::io::Cursor;
    use yosoi::{
        documents::ImageDocument,
        surface::{PixelArtifact, PixelOrientation},
    };

    let pixels = image::RgbaImage::from_pixel(8, 4, image::Rgba([12, 34, 56, 255]));
    let mut encoded = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgba8(pixels).write_to(&mut encoded, image::ImageFormat::Png)?;
    let mut bytes = encoded.into_inner();
    let mut offset = 8_usize;
    let mut corrupted = false;
    while let Some(header) = bytes.get(offset..offset.saturating_add(8)) {
        if header.len() != 8 {
            break;
        }
        let chunk_bytes = header.get(..4).ok_or("PNG chunk length is truncated")?;
        let chunk_len = u32::from_be_bytes(
            chunk_bytes
                .try_into()
                .map_err(|_| "PNG chunk length is invalid")?,
        );
        let chunk_type = header.get(4..8).ok_or("PNG chunk type is truncated")?;
        let data_offset = offset.checked_add(8).ok_or("PNG chunk offset overflow")?;
        if chunk_type == b"IDAT" {
            let value = bytes
                .get_mut(data_offset)
                .ok_or("PNG image data is empty")?;
            *value = 0;
            corrupted = true;
            break;
        }
        let chunk_size = usize::try_from(chunk_len).map_err(|_| "PNG chunk is too large")?;
        offset = data_offset
            .checked_add(chunk_size)
            .and_then(|end| end.checked_add(4))
            .ok_or("PNG chunk boundary overflow")?;
    }
    if !corrupted {
        return Err("PNG fixture has no IDAT chunk".into());
    }

    let document = ImageDocument::from_bytes("corrupt-pixels", bytes)?;
    assert!(
        PixelArtifact::from_image_document(document, 8, 4, PixelOrientation::ExifUnapplied,)
            .is_err()
    );
    Ok(())
}

#[cfg(feature = "surface-images")]
#[test]
fn jpeg_exif_orientation_remains_explicitly_unapplied() -> TestResult {
    use std::io::Cursor;
    use yosoi::{
        documents::ImageDocument,
        surface::{PixelArtifact, PixelLimits, PixelOrientation},
    };

    let pixels = image::RgbImage::from_fn(8, 4, |x, _| {
        if x < 4 {
            image::Rgb([220, 20, 30])
        } else {
            image::Rgb([20, 30, 220])
        }
    });
    let mut encoded = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgb8(pixels).write_to(&mut encoded, image::ImageFormat::Jpeg)?;
    let jpeg = encoded.into_inner();
    let header = jpeg.get(..2).ok_or("JPEG fixture is truncated")?;
    if header != [0xff, 0xd8] {
        return Err("JPEG fixture has no start-of-image marker".into());
    }
    let tail = jpeg.get(2..).ok_or("JPEG fixture is truncated")?;
    let exif = [
        b'E', b'x', b'i', b'f', 0, 0, b'I', b'I', 42, 0, 8, 0, 0, 0, 1, 0, 0x12, 0x01, 3, 0, 1, 0,
        0, 0, 6, 0, 0, 0, 0, 0, 0, 0,
    ];
    let segment_length = u16::try_from(exif.len().checked_add(2).ok_or("EXIF length overflow")?)?;
    let capacity = jpeg
        .len()
        .checked_add(exif.len())
        .and_then(|length| length.checked_add(4))
        .ok_or("EXIF JPEG allocation overflow")?;
    let mut with_exif = Vec::with_capacity(capacity);
    with_exif.extend_from_slice(header);
    with_exif.extend_from_slice(&[0xff, 0xe1]);
    with_exif.extend_from_slice(&segment_length.to_be_bytes());
    with_exif.extend_from_slice(&exif);
    with_exif.extend_from_slice(tail);

    let document = ImageDocument::from_bytes("exif-orientation-6", with_exif)?;
    let artifact = PixelArtifact::decode_image_document(document, PixelLimits::default())?;
    assert_eq!((artifact.info().width, artifact.info().height), (8, 4));
    assert_eq!(
        artifact.info().coordinate_space.orientation,
        PixelOrientation::ExifUnapplied
    );
    Ok(())
}

#[cfg(feature = "surface-images")]
#[test]
fn archived_legacy_video_pixels_keep_explicit_partial_source_identity() -> TestResult {
    use std::io::Cursor;
    use yosoi::{
        documents::ImageDocument,
        surface::{
            ArchiveLimits, ArchivedSource, Outcome, PixelArtifact, PixelCoordinateKind,
            PixelCoordinateSpace, PixelLimits, PixelOrientation, PixelSource,
        },
    };

    let pixels = image::RgbaImage::from_pixel(32, 16, image::Rgba([40, 90, 140, 255]));
    let mut encoded = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgba8(pixels).write_to(&mut encoded, image::ImageFormat::Png)?;
    let frame_image = ImageDocument::from_bytes("legacy-frame-pixels", encoded.into_inner())?;
    let artifact = PixelArtifact::from_raster_document(
        frame_image,
        PixelSource::LegacyVideoFrame {
            source_sha256: None,
            observation: "video-observation-legacy".into(),
            reference: "frame:350000".into(),
            requested_us: 350_000,
            source_pts_us: 400_000,
        },
        PixelCoordinateSpace {
            kind: PixelCoordinateKind::DecodedCanvas,
            width: 32,
            height: 16,
            orientation: PixelOrientation::DecoderApplied,
        },
    )?;
    let image_surface = ImageSurface::from_pixel_artifact(
        &artifact,
        32,
        Limits::default(),
        PixelLimits::default(),
    )?;
    let crop = image_surface.crop_rect(
        PixelRect {
            x: 8,
            y: 4,
            width: 12,
            height: 8,
        },
        100_000,
    )?;
    assert_eq!(crop.artifact.info().source, artifact.info().source);
    assert_eq!(
        crop.artifact.info().source_space.kind,
        PixelCoordinateKind::DecodedCanvas
    );

    let retained = ArchivedSource::new_pixel_artifact(
        artifact.info().identity.clone(),
        &artifact,
        32,
        Some(image_surface.index()),
    );
    let outcome =
        Outcome::new("legacy-frame-outcome", ArchiveLimits::default())?.with_source(retained)?;
    let restored = outcome.source_pixel_artifact(&artifact.info().identity, 1_048_576)?;
    assert_eq!(restored.info(), artifact.info());
    let restored_surface = outcome.surface(&artifact.info().identity, Limits::default())?;
    assert_eq!(
        restored_surface.identity(),
        image_surface.index().identity()
    );
    Ok(())
}

#[cfg(feature = "surface-video")]
#[tokio::test]
async fn image_session_opens_archived_video_pixels_without_video_or_source_path() -> TestResult {
    use std::io::Cursor;
    use yosoi::{
        Archive,
        documents::ImageDocument,
        surface::{
            ArchivePolicy, ImageSession, Limits, PixelArtifact, PixelCoordinateKind,
            PixelCoordinateSpace, PixelLimits, PixelOrientation, PixelSource, SurfaceConnection,
            SurfacePolicy,
        },
    };

    let pixels = image::RgbaImage::from_pixel(32, 16, image::Rgba([70, 80, 90, 255]));
    let mut encoded = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgba8(pixels).write_to(&mut encoded, image::ImageFormat::Png)?;
    let document = ImageDocument::from_bytes("archived-frame-pixels", encoded.into_inner())?;
    let artifact = PixelArtifact::from_raster_document(
        document,
        PixelSource::LegacyVideoFrame {
            source_sha256: None,
            observation: "old-video-observation".into(),
            reference: "frame:350000".into(),
            requested_us: 350_000,
            source_pts_us: 400_000,
        },
        PixelCoordinateSpace {
            kind: PixelCoordinateKind::DecodedCanvas,
            width: 32,
            height: 16,
            orientation: PixelOrientation::DecoderApplied,
        },
    )?;
    let archive_root = tempfile::tempdir()?;
    let archive = Archive::open(archive_root.path()).await?;
    let reference = artifact.write_to(&archive).await?;
    drop(archive);

    let output = tempfile::tempdir()?;
    let policy = SurfacePolicy {
        output: Some(output.path().to_owned()),
        archive: ArchivePolicy::Enabled,
        archive_root: Some(archive_root.path().to_owned()),
        ..SurfacePolicy::default()
    };
    let mut session = ImageSession::open_pixel_artifact(
        &reference,
        archive_root.path(),
        policy,
        32,
        Limits::default(),
        PixelLimits::default(),
    )
    .await?;
    let ready = session.ready()?;
    assert_eq!(
        ready
            .pointer("/state/descriptor/representation")
            .and_then(serde_json::Value::as_str),
        Some("yosoi.image.raster.v1")
    );
    let direct = session
        .execute(serde_json::json!({"op":"image_direct"}))
        .await?;
    assert_eq!(
        direct
            .pointer("/artifact/info/source/kind")
            .and_then(serde_json::Value::as_str),
        Some("legacy_video_frame")
    );
    assert_eq!(
        direct
            .pointer("/artifact/info/source/source_pts_us")
            .and_then(serde_json::Value::as_i64),
        Some(400_000)
    );
    let outcome = session
        .close()
        .await?
        .ok_or("image archive policy did not return its Outcome")?;
    let expected_surface_identity = outcome
        .surface(&artifact.info().identity, Limits::default())?
        .identity()
        .to_owned();
    archive_root.close()?;
    outcome.validate()?;
    let retained = outcome.source_pixel_artifact(&artifact.info().identity, 1_048_576)?;
    assert_eq!(retained.info(), artifact.info());
    let portable_archive_root = tempfile::tempdir()?;
    let portable_archive = Archive::open(portable_archive_root.path()).await?;
    let portable_path = output.path().join("surface.yosoi");
    let imported_reference = portable_archive.import_file(&portable_path).await?;
    let imported = portable_archive.read(&imported_reference).await?;
    let restored_surface = imported.surface(&artifact.info().identity, Limits::default())?;
    assert_eq!(restored_surface.identity(), expected_surface_identity);
    Ok(())
}

#[cfg(any(feature = "browser", feature = "surface-video"))]
#[tokio::test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions verify file-backed session identity through closed portable replay."
)]
async fn file_backed_image_session_restores_its_exact_index_after_move()
-> Result<(), Box<dyn Error>> {
    use std::{fs, io::Cursor};
    use yosoi::SurfaceConnection;
    use yosoi::{
        Archive,
        documents::ImageDocument,
        surface::{ArchivePolicy, ImageSession, ImageSurface, PixelLimits, SurfacePolicy},
    };
    let root = tempfile::tempdir()?;
    let file = root.path().join("source.png");
    let archive_root = root.path().join("archive");
    let output = root.path().join("output");
    let mut encoded = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgba8(image::RgbaImage::from_pixel(
        32,
        16,
        image::Rgba([20, 30, 40, 255]),
    ))
    .write_to(&mut encoded, image::ImageFormat::Png)?;
    let bytes = encoded.into_inner();
    fs::write(&file, &bytes)?;
    let document = ImageDocument::from_bytes("image-surface", bytes)?;
    let expected = ImageSurface::from_image_document(
        &document,
        32,
        Limits::default(),
        PixelLimits::default(),
    )?;
    let key = expected.source_artifact().info().identity.clone();
    let identity = expected.index().identity().to_owned();
    let mut session = ImageSession::open(
        &file,
        SurfacePolicy {
            output: Some(output.clone()),
            archive_root: Some(archive_root.clone()),
            archive: ArchivePolicy::Enabled,
            ..SurfacePolicy::default()
        },
        32,
        Limits::default(),
        PixelLimits::default(),
    )
    .await?;
    let outcome = session
        .close()
        .await?
        .ok_or("closed image Outcome missing")?;
    assert_eq!(
        outcome.surface(&key, Limits::default())?.identity(),
        identity
    );
    fs::remove_file(file)?;
    fs::remove_dir_all(archive_root)?;
    let archive = Archive::open(root.path().join("moved")).await?;
    let reference = archive.import_file(output.join("surface.yosoi")).await?;
    let moved = archive.read(&reference).await?;
    assert_eq!(moved.surface(&key, Limits::default())?.identity(), identity);
    Ok(())
}
