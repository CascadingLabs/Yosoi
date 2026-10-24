//! Local walkthrough of Rust Surface reads and sessions. No browser/model is launched.
#[path = "surface_walkthrough/fixtures.rs"]
mod fixtures;

use serde_json::{Value, json};
use std::{env, error::Error, fs, io, path::PathBuf, time::Instant};
use yosoi::{
    documents::Document,
    surface::{ActionStatus, Budget, Limits, Reference, Session, SessionPolicy, Surface},
};

fn found(index: &Surface, text: &str) -> Result<Reference, Box<dyn Error>> {
    index
        .find(text, None, Budget::default())?
        .entries
        .first()
        .map(|entry| entry.reference.clone())
        .ok_or_else(|| io::Error::other("fixture text absent").into())
}
fn parent(index: &Surface, reference: &Reference) -> Result<Reference, Box<dyn Error>> {
    index
        .parent(reference)?
        .ok_or_else(|| io::Error::other("fixture parent absent").into())
}
fn html(text: &str) -> Result<Surface, Box<dyn Error>> {
    Ok(Surface::new(&Document::html(
        "session-example",
        text.as_bytes().to_vec(),
    )?)?)
}

fn session_demo() -> Result<Value, Box<dyn Error>> {
    let before = html(
        "<main><article id='product'><h2>Needle lamp</h2><p>Specifications: ceramic</p><p>Stock 3</p><button>Add lamp</button></article><aside>Cart zero</aside></main>",
    )?;
    let session = Session::new(
        before.clone(),
        SessionPolicy {
            cursors: 3,
            ..SessionPolicy::default()
        },
    )?;
    let actor = session.cursor()?;
    let cart_reader = session.cursor()?;
    let details_reader = session.cursor()?;
    let detached = actor.status()?;
    session.attach()?;
    let live = actor.status()?;
    let button = parent(&before, &found(&before, "Add lamp")?)?;
    actor.inspect(&button, None, Budget::default())?;
    let cart = parent(&before, &found(&before, "Cart zero")?)?;
    let cart_watch = cart_reader.subscribe(&cart)?;
    let specifications = parent(&before, &found(&before, "Specifications: ceramic")?)?;
    let details_watch = details_reader.subscribe(&specifications)?;
    details_reader.inspect(&specifications, None, Budget::default())?;
    actor.promote()?;
    let rejected_second_owner = details_reader.promote().is_err();
    let hot = actor.status()?;
    let mut effect = actor.begin_action()?;
    effect.mark_dispatched()?;
    // Simulated adapter boundary. The native QScrape run supplies real browser effects separately.
    session.invalidate("fixture adapter reports a mutation; capture pending")?;
    let pending = details_reader.status()?;
    let after = html(
        "<main><article id='product'><h2>Needle lamp</h2><p>Specifications: ceramic</p><p>Stock 2</p><button>Add lamp</button></article><aside>Cart one</aside></main>",
    )?;
    session.publish(after.clone())?;
    let cart_change =
        cart_reader.reconcile(cart_watch, &parent(&after, &found(&after, "Cart one")?)?)?;
    let specification_change = details_reader.reconcile(
        details_watch,
        &parent(&after, &found(&after, "Specifications: ceramic")?)?,
    )?;
    let receipt = effect.finish(
        ActionStatus::Confirmed,
        "simulated adapter postcondition: cart zero to one",
    )?;
    let actor_after = actor.status()?;
    actor.cool()?;
    details_reader.promote()?;
    let handoff = details_reader.status()?;
    Ok(
        json!({"effects":"simulated in this CLI; see native QScrape browser evidence for actual interactions","detached":detached,"live_reader":live,"hot":hot,"second_hot_owner_rejected":rejected_second_owner,"capture_pending":pending,"cart_change":cart_change,"specifications_change":specification_change,"receipt":receipt,"actor_after":actor_after,"handoff":handoff,"cart_events":cart_reader.events()?,"details_events":details_reader.events()?}),
    )
}

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = env::args().collect();
    let value = |flag: &str| {
        args.iter()
            .position(|argument| argument == flag)
            .and_then(|position| args.get(position.saturating_add(1)))
    };
    let count = value("--records")
        .map(|value| value.parse::<usize>())
        .transpose()?
        .unwrap_or(1000);
    if !(1..=10000).contains(&count) {
        return Err(io::Error::other("records must be 1..=10000").into());
    }
    let output =
        value("--output").map_or_else(|| PathBuf::from(".local/overnight/sdk"), PathBuf::from);
    fs::create_dir_all(&output)?;
    let mut matrix = Vec::new();
    let mut document_view = None;
    for document in fixtures::documents(count)? {
        let start = Instant::now();
        let index = Surface::new(&document)?;
        let prepare_us = start.elapsed().as_micros();
        if document_view.is_none() {
            document_view = Some(index.clone());
        }
        let overview = index.overview(None, Budget::default())?;
        let matches = index.find("Needle lamp", None, Budget::default())?;
        let reference = matches
            .entries
            .first()
            .ok_or_else(|| io::Error::other("needle not found"))?
            .reference
            .clone();
        let detail = index.inspect(&reference, None, Budget::default())?;
        matrix.push(json!({"representation":index.representation(),"source_bytes":index.source_bytes(),"nodes":index.node_count(),"prepare_us":prepare_us,"overview_bytes":serde_json::to_vec(&overview)?.len(),"overview_population":overview.total,"overview":overview,"matches":matches,"inspection":detail,"native_coordinate":index.coordinate(&reference)?}));
    }
    let image_bytes = if let Some(path) = value("--image") {
        fs::read(path)?
    } else {
        let pixels = image::RgbaImage::from_fn(512, 256, |x, y| {
            if x < 256 && y < 128 {
                image::Rgba([255, 0, 0, 255])
            } else {
                image::Rgba([0, 0, 255, 255])
            }
        });
        let mut bytes = io::Cursor::new(Vec::new());
        image::DynamicImage::ImageRgba8(pixels).write_to(&mut bytes, image::ImageFormat::Png)?;
        bytes.into_inner()
    };
    fs::write(output.join("input-image.png-or-jpeg"), &image_bytes)?;
    let image = Surface::from_image(&image_bytes, 128, Limits::default())?;
    let image_overview = image.overview(None, Budget::default())?;
    let regions = image.expand(&image.root(), None, Budget::default())?;
    let mut crops = Vec::new();
    for (position, entry) in regions.entries.iter().enumerate() {
        let crop = image.crop(&entry.reference, 2 * 1024 * 1024)?;
        let path = output.join(format!("image-region-{position}.png"));
        fs::write(&path, &crop.png)?;
        crops.push(json!({"reference":crop.reference,"rect":crop.rect,"png_bytes":crop.png.len(),"path":path}));
    }
    let combined = Surface::combine(
        "independent teaching inputs; not a same-world atomic capture",
        vec![
            (
                "document".into(),
                document_view.ok_or_else(|| io::Error::other("document view missing"))?,
            ),
            ("screenshot".into(), image),
        ],
        Limits::default(),
    )?;
    let combined_manifest = combined.inspect(&combined.root(), None, Budget::default())?;
    let combined_views = combined.expand(&combined.root(), None, Budget::default())?;
    let result = json!({"records_per_representation":count,"build":"debug; workstation-local; no token or memory performance claim","documents":matrix,"multiple_cursors":session_demo()?,"combined":{"manifest":combined_manifest,"views":combined_views},"image":{"semantics":"pixel regions and actual crops only; no OCR/vision inference","overview":image_overview,"regions":regions,"crops":crops}});
    fs::write(
        output.join("results.json"),
        serde_json::to_vec_pretty(&result)?,
    )?;
    println!(
        "{}",
        serde_json::to_string_pretty(
            &json!({"output":output,"document_classes":matrix.len(),"records":count,"cursor_demo":"three readers, one hot owner, explicit scoped reconciliation","image_regions":crops.len()})
        )?
    );
    Ok(())
}
