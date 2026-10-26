//! Native visual transactions exercise real pixels, restoration and cancellation.
#![allow(
    clippy::panic_in_result_fn,
    reason = "Regression assertions; setup failures propagate."
)]

use super::active_navigation::Fixture;
use crate::browser::{BrowserConfig, BrowserEngine, MoliProfile};
use crate::internal::browser::bidi::session::{Page, Session, SessionError};
use crate::internal::browser::selector::{BrowserTarget, BrowserTargetKind};
use crate::internal::browser::{Bbox, ScreenshotOptions, Viewport, viewport::ScrollTarget};
use serde_json::{Value, json};
use std::{env, error::Error, time::Duration};
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

type TestResult = Result<(), Box<dyn Error + Send + Sync>>;
const STATE: &str =
    "({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,x:scrollX,y:scrollY})";
const FIXTURE: &str = "(()=>{const node=document.createElement('div');node.style.cssText='position:absolute;left:0;top:0;width:1800px;height:3000px;z-index:99999';node.innerHTML='<div style=\"position:absolute;top:0;width:1800px;height:300px;background:rgb(255,0,0)\"></div><div style=\"position:absolute;top:300px;width:1800px;height:2700px;background:rgb(0,255,0)\"></div><div id=\"visual-a\" class=\"visual-choice\" style=\"position:absolute;left:20px;top:650px;width:50px;height:40px;background:rgb(0,0,255)\"></div><div id=\"visual-b\" class=\"visual-choice\" style=\"position:absolute;left:100px;top:650px;width:30px;height:20px;background:rgb(255,255,0)\"></div><div id=\"visual-hidden\" class=\"visual-choice\" style=\"display:none;width:50px;height:40px\"></div>';document.body.append(node);return true})()";

async fn state(
    page: &Page,
    token: &CancellationToken,
    deadline: Instant,
) -> Result<Value, SessionError> {
    Ok(page.evaluate(STATE, token, deadline).await?.0)
}

async fn exercise(engine: BrowserEngine) -> TestResult {
    let fixture = Fixture::start().await;
    let token = CancellationToken::new();
    let deadline = Instant::now()
        .checked_add(Duration::from_secs(40))
        .ok_or("deadline")?;
    let headful = engine == BrowserEngine::Firefox
        && env::var("YOSOI_BIDI_MODE").is_ok_and(|mode| mode == "headful");
    let session = Session::launch(
        BrowserConfig {
            engine,
            moli_profile: if engine == BrowserEngine::Moli {
                MoliProfile::Layout
            } else {
                MoliProfile::Dom
            },
            moli_allow_private_networks: engine == BrowserEngine::Moli,
            ..BrowserConfig::default()
        },
        headful,
        None,
        &token,
        deadline,
    )
    .await?;
    let result = async {
        let user = session.new_user_context(&token, deadline).await?;
        let page = session.new_page(&user, &token, deadline).await?;
        page.navigate(&fixture.url("/normal"), "complete", &token, deadline).await?;
        page.evaluate(FIXTURE, &token, deadline).await?;
        let initial = state(&page, &token, deadline).await?;
        let mut temporary = Viewport::custom(640, 480);
        temporary.device_scale_factor = 2.0;
        let capture = page.visual_snapshot(ScreenshotOptions::default()
            .with_viewport(temporary.clone())
            .with_scroll(ScrollTarget::Pixels(400))
            .with_bbox(Bbox { x:10, y:10, width:40, height:30 }), &token, deadline).await?;
        assert_eq!((capture.image_width_pixels,capture.image_height_pixels),(80,60));
        assert_eq!(capture.capture_viewport.width_css_pixels().get(),640);
        assert_eq!(capture.device_scale_factor,2.0);
        let pixels = image::load_from_memory(capture.bytes())?.to_rgba8();
        assert_eq!(pixels.get_pixel_checked(0,0).ok_or("empty image")?.0,[0,255,0,255], "crop must include the actual scroll offset");
        assert_eq!(state(&page, &token, deadline).await?, initial, "default viewport must be reset, not pinned to the temporary one");
        drop(pixels);
        drop(capture);

        let mut persistent = Viewport::custom(800,600);
        persistent.device_scale_factor = 1.5;
        page.set_viewport(persistent, &token, deadline).await?;
        page.evaluate("window.scrollTo({left:50,top:200,behavior:'instant'});true", &token, deadline).await?;
        let before = state(&page, &token, deadline).await?;
        assert_eq!(before.get("y"),Some(&json!(200)));
        let capture = page.visual_snapshot(ScreenshotOptions::default().viewport_only()
            .with_viewport(temporary.clone()).with_scroll(ScrollTarget::Viewports(1.0)), &token, deadline).await?;
        assert_eq!((capture.image_width_pixels,capture.image_height_pixels),(1280,960));
        assert_eq!(state(&page, &token, deadline).await?,before);
        drop(capture);

        // Finite caller input can exceed finite coordinates in the active
        // viewport. This fails after applying the temporary override.
        let failed = page.visual_snapshot(ScreenshotOptions::default()
            .with_viewport(temporary).with_scroll(ScrollTarget::Viewports(f64::MAX)), &token, deadline).await;
        assert!(matches!(failed,Err(SessionError::InvalidArgument{..})));
        assert_eq!(state(&page, &token, deadline).await?, before, "capture errors must restore both viewport and scroll");
        page.ensure_owned().await?;

        selector_crops(&page, &token, deadline).await?;
        rejected_targets(&page, &token, deadline).await?;
        bounded_targets(&page, &token, deadline).await?;

        if engine == BrowserEngine::Firefox {
            // Drain earlier resize events, then hold the renderer only after
            // this capture's viewport mutation has dispatched.
            page.evaluate("()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))", &token, deadline).await?;
            page.evaluate("addEventListener('resize',()=>{const request=new XMLHttpRequest();request.open('GET','/hold',false);request.send()},{once:true});true", &token, deadline).await?;
            let captured_page=page.clone();let captured_token=token.clone();
            let capture=tokio::spawn(async move {
                captured_page.visual_snapshot(ScreenshotOptions::default().with_viewport(Viewport::custom(320,240)), &captured_token, deadline).await
            });
            fixture.wait_until_held().await;
            assert!(!capture.is_finished());
            capture.abort();
            assert!(capture.await.is_err());
            fixture.release_held_navigation();
            assert!(page.ensure_owned().await.is_err(), "cancelled mutated pages must not be reusable");
        } else {
            page.close(&token, deadline).await?;
            session.remove_user_context(&user,&token,deadline).await?;
        }
        drop(page);
        Ok::<_,Box<dyn Error + Send + Sync>>(())
    }.await;
    let _ = session.close().await;
    drop(session);
    result
}

#[tokio::test]
#[ignore = "requires the qualified stock Firefox executable"]
async fn bidi_firefox_visual_transactions_restore_and_fence() -> TestResult {
    exercise(BrowserEngine::Firefox).await
}

#[tokio::test]
#[ignore = "requires the pinned Moli layout executable"]
async fn bidi_moli_visual_transactions_restore() -> TestResult {
    exercise(BrowserEngine::Moli).await
}

async fn selector_crops(page: &Page, token: &CancellationToken, deadline: Instant) -> TestResult {
    let before = state(page, token, deadline).await?;
    let mut temporary = Viewport::custom(640, 480);
    temporary.device_scale_factor = 2.0;
    let image = page
        .visual_snapshot(
            ScreenshotOptions::default()
                .with_viewport(temporary)
                .with_scroll(ScrollTarget::Pixels(600))
                .with_selector(target(BrowserTargetKind::Css, "#visual-a", None)),
            token,
            deadline,
        )
        .await?;
    assert_eq!(
        (image.image_width_pixels, image.image_height_pixels),
        (100, 80)
    );
    let pixels = image::load_from_memory(image.bytes())?.to_rgba8();
    assert_eq!(
        pixels
            .get_pixel_checked(0, 0)
            .ok_or("empty target image")?
            .0,
        [0, 0, 255, 255]
    );
    drop(pixels);
    drop(image);
    assert_eq!(state(page, token, deadline).await?, before);
    for (kind, value) in [
        (BrowserTargetKind::Xpath, "//*[@id='visual-a']"),
        (BrowserTargetKind::Attr, "#visual-a"),
    ] {
        let image = page
            .visual_snapshot(
                ScreenshotOptions::default()
                    .with_scroll(ScrollTarget::Pixels(600))
                    .with_selector(target(kind, value, None)),
                token,
                deadline,
            )
            .await?;
        assert_eq!(
            (image.image_width_pixels, image.image_height_pixels),
            (75, 60)
        );
    }
    let mut by_id = target(BrowserTargetKind::GlobalId, ".visual-choice", None);
    by_id.name = Some("visual-b".to_owned());
    for selector in [
        target(BrowserTargetKind::Css, ".visual-choice", Some(1)),
        by_id,
    ] {
        let image = page
            .visual_snapshot(
                ScreenshotOptions::default().with_selector(selector),
                token,
                deadline,
            )
            .await?;
        assert_eq!(
            (image.image_width_pixels, image.image_height_pixels),
            (45, 30)
        );
        let pixels = image::load_from_memory(image.bytes())?.to_rgba8();
        assert_eq!(
            pixels.get_pixel_checked(0, 0).ok_or("empty nth image")?.0,
            [255, 255, 0, 255]
        );
    }
    let mut point = target(BrowserTargetKind::Visual, "", None);
    point.x = Some(150.0);
    point.y = Some(30.0);
    let image = page
        .visual_snapshot(
            ScreenshotOptions::default().with_selector(point),
            token,
            deadline,
        )
        .await?;
    let pixels = image::load_from_memory(image.bytes())?.to_rgba8();
    assert_eq!(
        pixels.get_pixel_checked(0, 0).ok_or("empty point image")?.0,
        [255, 0, 0, 255]
    );
    drop(pixels);
    drop(image);
    assert_eq!(state(page, token, deadline).await?, before);
    Ok(())
}

async fn rejected_targets(page: &Page, token: &CancellationToken, deadline: Instant) -> TestResult {
    use crate::internal::browser::{VoidCrawlError, controller::Page as ControllerPage};
    let before = state(page, token, deadline).await?;
    let temporary = Viewport::custom(640, 480);
    let adapter = ControllerPage::Bidi(page.clone());
    let ambiguous = adapter
        .visual_snapshot(
            ScreenshotOptions::default()
                .with_viewport(temporary)
                .with_scroll(ScrollTarget::Pixels(600))
                .with_selector(target(BrowserTargetKind::Css, ".visual-choice", None)),
        )
        .await;
    assert!(matches!(
        ambiguous,
        Err(VoidCrawlError::AmbiguousSelector(_))
    ));
    drop(adapter);
    assert_eq!(
        state(page, token, deadline).await?,
        before,
        "ambiguous crops must restore capture state"
    );
    for value in ["#visual-hidden", "#missing"] {
        let result = page
            .visual_snapshot(
                ScreenshotOptions::default().with_selector(target(
                    BrowserTargetKind::Css,
                    value,
                    None,
                )),
                token,
                deadline,
            )
            .await;
        assert!(matches!(result, Err(SessionError::TargetNotVisible)));
    }
    let role = page
        .visual_snapshot(
            ScreenshotOptions::default().with_selector(target(
                BrowserTargetKind::Role,
                "button",
                None,
            )),
            token,
            deadline,
        )
        .await;
    assert!(matches!(
        role,
        Err(SessionError::Unsupported("BiDi AX-exposed role geometry"))
    ));
    let structured = page
        .visual_snapshot(
            ScreenshotOptions::default().with_selector(target(
                BrowserTargetKind::Jsonld,
                "Product",
                None,
            )),
            token,
            deadline,
        )
        .await;
    assert!(matches!(
        structured,
        Err(SessionError::UnsupportedVisualTarget)
    ));
    assert_eq!(state(page, token, deadline).await?, before);
    Ok(())
}

fn target(kind: BrowserTargetKind, value: &str, nth: Option<u32>) -> BrowserTarget {
    BrowserTarget {
        kind,
        value: value.to_owned(),
        regex: None,
        name: None,
        nth,
        x: None,
        y: None,
    }
}

async fn bounded_targets(page: &Page, token: &CancellationToken, deadline: Instant) -> TestResult {
    let before = state(page, token, deadline).await?;
    let mut outside = target(BrowserTargetKind::Visual, "", None);
    outside.x = Some(100_000.0);
    outside.y = Some(1.0);
    assert!(matches!(
        page.visual_snapshot(
            ScreenshotOptions::default().with_selector(outside),
            token,
            deadline
        )
        .await,
        Err(SessionError::TargetNotVisible)
    ));
    let incompatible = page
        .visual_snapshot(
            ScreenshotOptions::default()
                .with_bbox(Bbox {
                    x: 0,
                    y: 0,
                    width: 10,
                    height: 10,
                })
                .with_selector(target(BrowserTargetKind::Css, "#visual-a", None)),
            token,
            deadline,
        )
        .await;
    assert!(matches!(
        incompatible,
        Err(SessionError::InvalidArgument { .. })
    ));
    page.evaluate("(()=>{const root=document.createElement('div');root.id='bounded-targets';root.style.display='none';for(let i=0;i<4097;i++){const node=document.createElement('span');node.className='bounded-target';root.append(node)}document.body.append(root);return true})()",token,deadline).await?;
    assert!(matches!(
        page.visual_snapshot(
            ScreenshotOptions::default().with_selector(target(
                BrowserTargetKind::Css,
                ".bounded-target",
                None
            )),
            token,
            deadline
        )
        .await,
        Err(SessionError::Capacity)
    ));
    page.evaluate(
        "document.querySelector('#bounded-targets').remove();true",
        token,
        deadline,
    )
    .await?;
    assert_eq!(state(page, token, deadline).await?, before);
    Ok(())
}
