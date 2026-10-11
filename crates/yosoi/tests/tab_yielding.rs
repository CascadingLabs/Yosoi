#![cfg(feature = "browser")]
use std::{env, error::Error, future::Future, task::Poll, time::Duration};
use tokio::{sync::oneshot, time::timeout};
use yosoi::{
    flow::Condition,
    session::{self, ExecutionPool, SessionError, SessionPolicy},
};
#[path = "../examples/support/yield_fixture.rs"]
mod fixture;
type TestResult = Result<(), Box<dyn Error + Send + Sync>>;

#[tokio::test(flavor = "current_thread")]
async fn long_condition_wait_outlives_the_transport_default_while_other_work_progresses()
-> TestResult {
    if !enabled() {
        eprintln!("SKIPPED: opt in to browser proof");
        return Ok(());
    }
    let mut service = fixture::QuoteService::start(Some(Duration::from_secs(32))).await?;
    let pool = ExecutionPool::new(1, 4)?;
    let browser = session::new()
        .configure(settings(2))
        .execution_pool(&pool)
        .acquire()
        .await?;
    let a = browser.work().await?;
    let tab = browser.new_tab().await?;
    let b = tab.work().await?;
    a.navigate(&service.url(0)).await?;
    b.navigate(&service.url(1)).await?;
    a.click("#start").await?;
    timeout(Duration::from_secs(5), service.started.recv()).await??;
    let mut events = pool.subscribe();
    let recipe = yosoi::flow::new([yosoi::action::wait_until(
        Condition::Visible {
            selector: "#done".into(),
        },
        35_000,
    )])
    .timeout(40_000);
    let progress = async {
        while events.recv().await?.parked == 0 {}
        b.observe().await?;
        assert_eq!(pool.snapshot().active, 0);
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    };
    let started = tokio::time::Instant::now();
    let invocation = recipe.with_lease(&a);
    let (outcome, other) = timeout(Duration::from_secs(45), async {
        tokio::join!(invocation.invoke(), progress)
    })
    .await?;
    other?;
    let outcome = outcome?;
    assert_eq!(outcome.terminal, yosoi::flow::FlowTermination::Completed);
    assert!(started.elapsed() >= Duration::from_secs(30));
    assert_eq!(pool.snapshot().active, 0);
    assert_eq!(pool.snapshot().parked, 0);
    a.release().await?;
    b.release().await?;
    browser.close().await?;
    service.stop().await?;
    Ok(())
}
fn enabled() -> bool {
    env::var("YOSOI_BROWSER_TESTS").as_deref() == Ok("1")
}

#[tokio::test(flavor = "current_thread")]
async fn queued_deadline_is_predispatch_and_does_not_fence_the_tab() -> TestResult {
    if !enabled() {
        eprintln!("SKIPPED: opt in to browser proof");
        return Ok(());
    }
    let service = fixture::QuoteService::start(None).await?;
    let pool = ExecutionPool::new(1, 4)?;
    let browser = session::new().execution_pool(&pool).acquire().await?;
    let work = browser.work().await?;
    let held = pool.acquire().await?;
    let recipe = yosoi::flow::new([yosoi::action::navigate(service.url(0)).timeout(100)]);
    let outcome = recipe.with_lease(&work).invoke().await?;
    // Default continuation retains the rejected step without stopping the invocation.
    assert_eq!(
        outcome.terminal,
        yosoi::flow::FlowTermination::CompletedWithIssues
    );
    assert_eq!(
        outcome.steps.first().map(|step| step.receipt.status),
        Some(yosoi::automation_record::OperationStatus::Rejected)
    );
    assert_eq!(pool.snapshot().queued, 0);
    drop(held);
    work.navigate(&service.url(0)).await?;
    work.release().await?;
    browser.close().await?;
    service.stop().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn resumption_does_not_restart_the_deadline_or_hide_prior_dispatch() -> TestResult {
    if !enabled() {
        eprintln!("SKIPPED: opt in to browser proof");
        return Ok(());
    }
    let mut service = fixture::QuoteService::start(None).await?;
    let pool = ExecutionPool::new(1, 4)?;
    let browser = session::new().execution_pool(&pool).acquire().await?;
    let work = browser.work().await?;
    work.navigate(&service.url(0)).await?;
    work.click("#start").await?;
    timeout(Duration::from_secs(5), service.started.recv()).await??;
    let mut events = pool.subscribe();
    let recipe = yosoi::flow::new([yosoi::action::wait_until(
        Condition::Visible {
            selector: "#done".into(),
        },
        5_000,
    )])
    .timeout(700);
    let (done, waiting_done) = oneshot::channel();
    let invoke = async {
        let outcome = recipe.with_lease(&work).invoke().await;
        let _ = done.send(());
        outcome
    };
    let hold_resume = async {
        while events.recv().await?.parked == 0 {}
        let held = pool.acquire().await?;
        service.complete(0)?;
        waiting_done.await?;
        drop(held);
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    };
    let started = tokio::time::Instant::now();
    let (outcome, held) = timeout(Duration::from_secs(5), async {
        tokio::join!(invoke, hold_resume)
    })
    .await?;
    held?;
    let outcome = outcome?;
    assert_eq!(outcome.terminal, yosoi::flow::FlowTermination::Unknown);
    assert_eq!(
        outcome.steps.first().map(|step| step.receipt.status),
        Some(yosoi::automation_record::OperationStatus::Unknown)
    );
    assert!(started.elapsed() < Duration::from_secs(2));
    assert_eq!(pool.snapshot().queued, 0);
    assert_eq!(pool.snapshot().parked, 0);
    assert_eq!(pool.snapshot().active, 0);
    assert!(matches!(
        work.click("#start").await,
        Err(SessionError::Closed)
    ));
    work.release().await?;
    browser.close().await?;
    service.stop().await?;
    Ok(())
}
fn settings(tabs: u32) -> SessionPolicy {
    SessionPolicy {
        maximum_tabs: tabs,
        execution_concurrency: 1,
        ..SessionPolicy::default()
    }
}

#[tokio::test(flavor = "current_thread")]
async fn parked_tab_retains_ownership_while_another_tab_completes() -> TestResult {
    if !enabled() {
        eprintln!("SKIPPED: opt in to browser proof");
        return Ok(());
    }
    let mut service = fixture::QuoteService::start(None).await?;
    let pool = ExecutionPool::new(1, 4)?;
    let browser = session::new()
        .configure(settings(2))
        .execution_pool(&pool)
        .acquire()
        .await?;
    let a = browser.work().await?;
    let other_tab = browser.new_tab().await?;
    let b = other_tab.work().await?;
    a.navigate(&service.url(0)).await?;
    b.navigate(&service.url(1)).await?;
    a.click("#start").await?;
    assert_eq!(
        timeout(Duration::from_secs(5), service.started.recv()).await??,
        0
    );
    let condition = Condition::Visible {
        selector: "#done".into(),
    };
    let mut events = pool.subscribe();
    let mut a_wait = Box::pin(a.wait_until(&condition, 5_000));
    let mut contender = Box::pin(browser.work());
    let b_job = async {
        while events.recv().await?.parked == 0 {}
        b.click("#start").await?;
        assert_eq!(
            timeout(Duration::from_secs(5), service.started.recv()).await??,
            1
        );
        service.complete(1)?;
        let b_receipt = b
            .wait_until(
                &Condition::Visible {
                    selector: "#done".into(),
                },
                5_000,
            )
            .await?;
        assert_eq!(
            b_receipt.status,
            yosoi::automation_record::OperationStatus::Observed
        );
        // B is done, but A still waits for its service response and owns its tab.
        let snapshot = browser.execution_snapshot();
        assert_eq!(snapshot.parked, 1);
        assert_eq!(snapshot.active, 0);
        std::future::poll_fn(|cx| {
            assert!(matches!(contender.as_mut().poll(cx), Poll::Pending));
            Poll::Ready(())
        })
        .await;
        service.complete(0)?;
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    };
    let (a_receipt, b_result) = timeout(Duration::from_secs(10), async {
        tokio::join!(&mut a_wait, b_job)
    })
    .await?;
    b_result?;
    assert_eq!(
        a_receipt?.status,
        yosoi::automation_record::OperationStatus::Observed
    );
    drop(a_wait);
    a.release().await?;
    let replacement = timeout(Duration::from_secs(5), contender).await??;
    replacement.release().await?;
    b.release().await?;
    assert_eq!(browser.execution_snapshot().parked, 0);
    assert_eq!(browser.execution_snapshot().active, 0);
    browser.close().await?;
    service.stop().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn shared_pool_allows_progress_in_another_browser_process() -> TestResult {
    if !enabled() {
        eprintln!("SKIPPED: opt in to browser proof");
        return Ok(());
    }
    let pool = ExecutionPool::new(1, 4)?;
    let mut service = fixture::QuoteService::start(None).await?;
    let first = session::new().execution_pool(&pool).acquire().await?;
    let second = session::new().execution_pool(&pool).acquire().await?;
    let a = first.work().await?;
    let b = second.work().await?;
    a.navigate(&service.url(0)).await?;
    b.navigate(&service.url(1)).await?;
    a.click("#start").await?;
    timeout(Duration::from_secs(5), service.started.recv()).await??;
    let condition = Condition::Visible {
        selector: "#done".into(),
    };
    let mut events = pool.subscribe();
    let other = async {
        while events.recv().await?.parked == 0 {}
        b.click("#start").await?;
        assert_eq!(
            timeout(Duration::from_secs(5), service.started.recv()).await??,
            1
        );
        service.complete(1)?;
        b.wait_until(&condition, 5_000).await?;
        assert_eq!(pool.snapshot().parked, 1);
        assert!(pool.snapshot().peak_active <= 1);
        service.complete(0)?;
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    };
    let (waiting, progressed) = timeout(Duration::from_secs(10), async {
        tokio::join!(a.wait_until(&condition, 5_000), other)
    })
    .await?;
    waiting?;
    progressed?;
    a.release().await?;
    b.release().await?;
    first.close().await?;
    second.close().await?;
    assert_eq!(pool.snapshot().parked, 0);
    assert_eq!(pool.snapshot().active, 0);
    service.stop().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn dropping_parked_wait_fences_only_its_tab_and_returns_capacity() -> TestResult {
    if !enabled() {
        eprintln!("SKIPPED: opt in to browser proof");
        return Ok(());
    }
    let mut service = fixture::QuoteService::start(None).await?;
    let pool = ExecutionPool::new(1, 4)?;
    let browser = session::new()
        .configure(settings(2))
        .execution_pool(&pool)
        .acquire()
        .await?;
    let a = browser.work().await?;
    let tab = browser.new_tab().await?;
    let b = tab.work().await?;
    a.navigate(&service.url(0)).await?;
    b.navigate(&service.url(1)).await?;
    a.click("#start").await?;
    timeout(Duration::from_secs(5), service.started.recv()).await??;
    let mut events = pool.subscribe();
    let condition = Condition::Visible {
        selector: "#done".into(),
    };
    let mut waiting = Box::pin(a.wait_until(&condition, 5_000));
    let progress = async {
        while events.recv().await?.parked == 0 {}
        b.observe().await?;
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    };
    tokio::select! {
        result = &mut waiting => return Err(format!("wait unexpectedly settled: {result:?}").into()),
        result = progress => { result?; },
    }
    assert_eq!(browser.execution_snapshot().parked, 1);
    drop(waiting);
    assert_eq!(browser.execution_snapshot().parked, 0);
    assert_eq!(browser.execution_snapshot().active, 0);
    assert!(matches!(a.observe().await, Err(SessionError::Closed)));
    b.observe().await?;
    a.release().await?;
    b.release().await?;
    browser.close().await?;
    service.stop().await?;
    Ok(())
}
