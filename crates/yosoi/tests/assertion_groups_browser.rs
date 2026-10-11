#![cfg(feature = "browser")]
use std::{env, error::Error};
use yosoi::assertions as yosoi_assertions;
use yosoi::automation_record as yosoi_automation_record;
use yosoi::{
    action::{self, check},
    flow::{self, FlowTermination},
    policy::{Acquisition, BrowserMode, DocumentRequest, Page, Policy},
    prelude as ys, session,
};
#[path = "support/session_fixture.rs"]
mod fixture;

#[derive(ys::Contract)]
#[ys(id = "fixture", description = "One observed fixture")]
struct Fixture {
    #[ys(description="Status", locator=ys::locator::css("#status").text())]
    status: String,
    #[ys(description="Rows", locator=ys::locator::css(".row").text())]
    rows: Vec<String>,
}
#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn browser_group_captures_once_and_continues_to_next_click() -> Result<(), Box<dyn Error>> {
    if env::var("YOSOI_BROWSER_TESTS").ok().as_deref() != Some("1") {
        eprintln!("SKIPPED: requires browser opt-in");
        return Ok(());
    }
    let fixture = fixture::SessionFixture::start().await?;
    let policy = Policy {
        page: Page::new(vec![
            Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
        ])?,
        ..Policy::default()
    };
    let session = session::new().bind(&policy).acquire().await?;
    let lease = session.work().await?;
    lease.navigate(&fixture.url("/assertions")).await?;
    let failing = flow::new([
        action::assert_all::<Fixture>(
            Fixture::plan()?,
            [
                check(|page: &Fixture| page.rows.len() > 99),
                check(|page: &Fixture| page.status == "wrong"),
            ],
        )
        .into(),
        action::click("#advance"),
    ]);
    let outcome = failing.with_lease(&lease).invoke().await?;
    assert_eq!(outcome.terminal, FlowTermination::CompletedWithIssues);
    assert_eq!(outcome.steps.len(), 2);
    let receipt = &outcome.steps.first().ok_or("missing receipt")?.receipt;
    let report: yosoi_assertions::AssertionReport =
        serde_json::from_value(receipt.result.clone().ok_or("missing report")?)?;
    assert_eq!(
        report
            .checks
            .iter()
            .map(|check| check.passed)
            .collect::<Vec<_>>(),
        [Some(false), Some(false)]
    );
    let observation = receipt.observation.as_ref().ok_or("missing observation")?;
    match &report.located {
        ys::LocateOutcome::Matched { result } => {
            assert_eq!(result.document_id().as_str(), observation.id);
        }
        _ => return Err("missing located evidence".into()),
    }
    assert_eq!(
        outcome.steps.get(1).map(|step| step.receipt.status),
        Some(yosoi_automation_record::OperationStatus::Observed)
    );
    let passing = flow::new([
        action::assert_all::<Fixture>(
            Fixture::plan()?,
            [
                check(|page: &Fixture| page.rows.len() == 12),
                check(|page: &Fixture| page.status == "idle"),
            ],
        )
        .into(),
        action::click("#advance"),
        action::assert_all::<Fixture>(
            Fixture::plan()?,
            [check(|page: &Fixture| page.status == "ready")],
        )
        .into(),
    ]);
    assert_eq!(
        passing.with_lease(&lease).invoke().await?.terminal,
        FlowTermination::Completed
    );
    lease.release().await?;
    session.close().await?;
    fixture.shutdown().await?;
    Ok(())
}
