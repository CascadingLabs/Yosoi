#![allow(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Assertions describe acceptance; settled owners intentionally remain live through cleanup assertions."
)]

use super::*;
use crate::browser::BrowserConfig;
use crate::internal::browser::bidi::{session::Session, transport::EventStream};
use std::{error::Error, result::Result as StdResult};

async fn delivered(
    events: &mut EventStream,
    context: &str,
    count: usize,
    token: &CancellationToken,
    deadline: Instant,
) -> StdResult<(), Box<dyn Error + Send + Sync>> {
    let mut received = 0;
    while received < count {
        let event = events.next(token, deadline).await?;
        if event.method == "log.entryAdded"
            && event
                .params
                .pointer("/source/context")
                .and_then(Value::as_str)
                == Some(context)
        {
            received = received.checked_add(1).ok_or("count")?;
        }
    }
    Ok(())
}

async fn native_runtime(engine: BrowserEngine) -> StdResult<(), Box<dyn Error + Send + Sync>> {
    let token = CancellationToken::new();
    let deadline = Instant::now()
        .checked_add(Duration::from_secs(25))
        .ok_or("deadline")?;
    let session = Session::launch(
        BrowserConfig {
            engine,
            ..BrowserConfig::default()
        },
        false,
        &token,
        deadline,
    )
    .await?;
    let result=async {
        let user=session.new_user_context(&token,deadline).await?;
        let page=session.new_page(&user,&token,deadline).await?;
        let mut events=session.connection.subscribe()?;
        let options=ObservationOptions {collect_network:false,collect_console:true,collect_exceptions:true,max_events:8,..ObservationOptions::default()};
        let scope=ObservationScope::arm_bidi(page.clone(),options).await?;
        page.evaluate("console.log('native-runtime-log');setTimeout(()=>{globalThis.__runtime_timer_fired=true;throw new Error('native-runtime-boom')},0);true",&token,deadline).await?;
        assert_eq!(page.evaluate("new Promise(resolve=>setTimeout(()=>resolve(!!globalThis.__runtime_timer_fired),0))",&token,deadline).await?.0,serde_json::json!(true));
        delivered(&mut events,&page.context,if engine==BrowserEngine::Firefox {2}else{1},&token,deadline).await?;
        let report=scope.finish().await?;
        assert_eq!(report.termination,ObservationTermination::Finished);
        assert!(report.cleanup_complete);
        assert_ne!(report.diagnostics,Vec::new());
        assert!(report.diagnostics.iter().any(|entry|matches!(&entry.kind,RuntimeDiagnosticKind::Console {level} if level=="log") && entry.text().text().is_some_and(|text|text.contains("native-runtime-log"))));
        if engine==BrowserEngine::Firefox {
            assert!(report.diagnostics.iter().any(|entry|entry.kind==RuntimeDiagnosticKind::Exception && entry.text().text().is_some_and(|text|text.contains("native-runtime-boom"))));
            assert_eq!(report.accounting.runtime_events.dropped,MeasuredCount::Known {value:0});
        } else {
            assert!(matches!(report.accounting.runtime_events.dropped,MeasuredCount::Unavailable {..}));
            assert!(matches!(report.accounting.runtime_bytes.dropped,MeasuredCount::Unavailable {..}));
        }

        let scope=ObservationScope::arm_bidi(page.clone(),ObservationOptions {collect_exceptions:false,max_diagnostic_bytes:4,..options}).await?;
        page.evaluate("console.log('é漢字');true",&token,deadline).await?;
        delivered(&mut events,&page.context,1,&token,deadline).await?;
        let report=scope.finish().await?;
        assert!(report.cleanup_complete);
        let entry=report.diagnostics.first().ok_or("diagnostic")?;
        assert_eq!(entry.text().text(),Some("é"));
        assert_eq!(entry.complete_bytes,8);
        assert_eq!(report.diagnostic_bytes_retained,2);
        assert_eq!(report.diagnostic_bytes_dropped,6);
        page.close(&token,deadline).await?;
        session.remove_user_context(&user,&token,deadline).await?;
        Ok::<_,Box<dyn Error+Send+Sync>>(())
    }.await;
    let cleanup = session.close().await;
    result?;
    cleanup?;
    Ok(())
}

#[test]
fn nullable_log_text_is_not_an_empty_diagnostic() -> Result<()> {
    let event = BidiEvent {
        sequence: 1,
        method: "log.entryAdded".to_owned(),
        params: serde_json::json!({"type":"console","method":"warn","level":"warn","text":null}),
    };
    let (signal, unknown) = runtime_signal(&event, ObservationOptions::default())?
        .ok_or_else(|| VoidCrawlError::PageError("signal".to_owned()))?;
    assert!(unknown);
    assert!(matches!(
        signal,
        RawSignal::Event {
            kind: ObservationEventKind::ConsoleApiCalled,
            diagnostic: None,
            ..
        }
    ));
    Ok(())
}

#[tokio::test]
#[ignore = "requires qualified stock Firefox"]
async fn firefox_console_exception_and_utf8_retention()
-> StdResult<(), Box<dyn Error + Send + Sync>> {
    native_runtime(BrowserEngine::Firefox).await
}

#[tokio::test]
#[ignore = "requires pinned Moli"]
async fn moli_console_exception_and_utf8_retention() -> StdResult<(), Box<dyn Error + Send + Sync>>
{
    native_runtime(BrowserEngine::Moli).await
}
