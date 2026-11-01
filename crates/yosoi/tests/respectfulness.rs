#![allow(
    clippy::panic_in_result_fn,
    reason = "Assertions intentionally fail behavioral SDK tests."
)]

use std::{
    error::Error,
    io,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
};

use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    sync::{Notify, oneshot},
    task::JoinHandle,
    time::{Duration, timeout},
};
use yosoi::{prelude as ys, request::Attempt};
use ys::{
    policy::respectfulness::{Cooldown, EventKind, Group, RateBudget, Respectfulness, Retry},
    registry::Registry,
};

type TestResult = Result<(), Box<dyn Error>>;

async fn server(
    responses: Vec<&'static str>,
) -> Result<(String, Arc<AtomicUsize>, JoinHandle<()>), Box<dyn Error>> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let url = format!("http://{}/", listener.local_addr()?);
    let calls = Arc::new(AtomicUsize::new(0));
    let observed = calls.clone();
    let task = tokio::spawn(async move {
        for response in responses {
            let Ok((mut stream, _)) = listener.accept().await else {
                return;
            };
            let mut data = Vec::new();
            let mut buffer = [0_u8; 1024];
            loop {
                let Ok(count) = stream.read(&mut buffer).await else {
                    return;
                };
                if count == 0 {
                    return;
                }
                let Some(chunk) = buffer.get(..count) else {
                    return;
                };
                data.extend_from_slice(chunk);
                if data.windows(4).any(|window| window == b"\r\n\r\n") {
                    break;
                }
                if data.len() > 8192 {
                    return;
                }
            }
            observed.fetch_add(1, Ordering::SeqCst);
            let _ = stream.write_all(response.as_bytes()).await;
        }
    });
    Ok((url, calls, task))
}

#[tokio::test(flavor = "current_thread")]
async fn concurrency_lease_covers_the_response_body() -> TestResult {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let url = format!("http://{}/", listener.local_addr()?);
    let release = Arc::new(Notify::new());
    let (started, observed) = oneshot::channel();
    let released = release.clone();
    let task = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await?;
        let mut head = Vec::new();
        let mut byte = [0_u8];
        while !head.ends_with(b"\r\n\r\n") {
            stream.read_exact(&mut byte).await?;
            head.extend_from_slice(&byte);
            if head.len() > 8192 {
                return Err(io::Error::other("oversized test head"));
            }
        }
        stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\nConnection: close\r\n\r\nh").await?;
        let _ = started.send(());
        released.notified().await;
        stream.write_all(b"i").await?;
        Ok::<_, io::Error>(())
    });
    let policy = ys::Policy {
        respectfulness: Some(Respectfulness::new(vec![group(&url)])?),
        ..ys::Policy::default()
    };
    let directory = tempfile::tempdir()?;
    let registry = Registry::jsonl(directory.path().join("registry.jsonl"))?;
    let first_policy = policy.clone();
    let first_registry = registry.clone();
    let first_url = url.clone();
    let first = tokio::spawn(async move {
        ys::request::new(first_url)
            .bind(&first_policy)
            .with_registry(&first_registry)
            .send()
            .await
    });
    timeout(Duration::from_secs(3), observed).await??;
    let rejected = timeout(
        Duration::from_secs(3),
        ys::request::new(url)
            .bind(&policy)
            .with_registry(&registry)
            .send(),
    )
    .await??;
    assert!(
        rejected
            .respectfulness()
            .iter()
            .any(|event| event.error.as_ref().is_some_and(|error| matches!(
                error,
                ys::policy::respectfulness::RespectfulnessError::Limited {
                    reason: ys::policy::respectfulness::LimitReason::Concurrency,
                    ..
                }
            )))
    );
    release.notify_one();
    let first_response = first.await??;
    assert_eq!(
        first_response.attempts().next().and_then(Attempt::status),
        Some(200),
        "{:?}",
        first_response.respectfulness()
    );
    task.await??;
    Ok(())
}

fn group(url: &str) -> Group {
    Group {
        concurrency: Some(1),
        ..Group::new("sdk-loopback", [format!("^{}", regex::escape(url))])
    }
}

#[tokio::test(flavor = "current_thread")]
async fn sdk_spacing_rejection_precedes_a_second_outbound_request() -> TestResult {
    let (url, calls, task) = server(vec!["HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\nConnection: close\r\n\r\nhi"]).await?;
    let group = Group {
        spacing_ms: Some(60_000),
        ..group(&url)
    };
    let mut respect = Respectfulness::new(vec![group])?;
    let directory = tempfile::tempdir()?;
    respect.registry_path = Some(directory.path().join("registry.jsonl"));
    let policy = ys::Policy {
        respectfulness: Some(respect),
        ..ys::Policy::default()
    };
    let first = ys::request::new(url.clone()).bind(&policy).send().await?;
    assert_eq!(first.attempts().next().and_then(Attempt::status), Some(200));
    let second = ys::request::new(url).bind(&policy).send().await?;
    assert!(
        second
            .respectfulness()
            .iter()
            .any(|event| event.kind == EventKind::Rejected)
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    task.await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn explicit_retry_preserves_prior_429_and_charges_both_starts() -> TestResult {
    let (url, calls, task) = server(vec![
        "HTTP/1.1 429 Too Many Requests\r\nRetry-After: 0\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\nConnection: close\r\n\r\nhi",
    ]).await?;
    let group = Group {
        budgets: vec![RateBudget {
            requests: 2,
            window_ms: 60_000,
        }],
        cooldown: Some(Cooldown {
            statuses: vec![429],
            fallback_ms: 1000,
            transport_errors: false,
        }),
        ..group(&url)
    };
    let mut respect = Respectfulness::new(vec![group])?;
    respect.retry = Retry {
        max_attempts: 2,
        statuses: vec![429],
        backoff_ms: 1,
        transport_errors: false,
    };
    let policy = ys::Policy {
        respectfulness: Some(respect),
        ..ys::Policy::default()
    };
    let directory = tempfile::tempdir()?;
    let registry = Registry::jsonl(directory.path().join("registry.jsonl"))?;
    let response = ys::request::new(url.clone())
        .bind(&policy)
        .with_registry(&registry)
        .send()
        .await?;
    assert_eq!(
        response.attempts().next().and_then(Attempt::status),
        Some(200)
    );
    let statuses: Vec<_> = response
        .respectfulness()
        .iter()
        .filter(|event| event.kind == EventKind::Response)
        .filter_map(|event| event.status)
        .collect();
    assert_eq!(statuses, vec![429, 200]);
    assert_eq!(
        response
            .respectfulness()
            .iter()
            .filter(|event| event.kind == EventKind::Admitted)
            .count(),
        2
    );
    let rejected = ys::request::new(url)
        .bind(&policy)
        .with_registry(&registry)
        .send()
        .await?;
    assert!(
        rejected
            .respectfulness()
            .iter()
            .any(|event| event.kind == EventKind::Rejected)
    );
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    task.await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn redirect_hop_requires_its_own_admission() -> TestResult {
    let (url, calls, task) = server(vec![
        "HTTP/1.1 302 Found\r\nLocation: /two\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\nConnection: close\r\n\r\nhi",
    ]).await?;
    let group = Group {
        budgets: vec![RateBudget {
            requests: 1,
            window_ms: 60_000,
        }],
        ..group(&url)
    };
    let policy = ys::Policy {
        respectfulness: Some(Respectfulness::new(vec![group])?),
        ..ys::Policy::default()
    };
    let directory = tempfile::tempdir()?;
    let registry = Registry::jsonl(directory.path().join("registry.jsonl"))?;
    let response = ys::request::new(url)
        .bind(&policy)
        .with_registry(&registry)
        .send()
        .await?;
    assert!(
        response
            .respectfulness()
            .iter()
            .any(|event| event.kind == EventKind::Rejected)
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    task.abort();
    Ok(())
}

#[test]
fn policy_identity_and_wire_keep_disabled_behavior_compatible() -> TestResult {
    let ordinary = ys::Policy::default();
    assert!(!ordinary.to_canonical_json()?.contains("respectfulness"));
    assert_eq!(ordinary.effective_identity()?.version(), 7);
    let policy = ys::Policy {
        respectfulness: Some(Respectfulness::new(vec![group("http://example.com/")])?),
        ..ys::Policy::default()
    };
    assert_eq!(policy.effective_identity()?.version(), 9);
    let restored: ys::Policy = serde_json::from_str(&policy.to_canonical_json()?)?;
    assert_eq!(restored, policy);
    assert_eq!(restored.effective_identity()?, policy.effective_identity()?);
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn registry_failure_prevents_requests_and_search_and_explicit_handle_overrides_path()
-> TestResult {
    use ys::policy::search::{Provider, ProviderRequestProfile, ProviderSelection};
    let directory = tempfile::tempdir()?;
    let corrupt = directory.path().join("corrupt.jsonl");
    std::fs::write(&corrupt, "broken\n")?;
    let mut respect = Respectfulness::new(vec![Group {
        blocked: true,
        ..Group::new("blocked", ["^https?://"])
    }])?;
    respect.registry_path = Some(corrupt);
    let mut policy = ys::Policy {
        respectfulness: Some(respect),
        ..ys::Policy::default()
    };
    policy.search.providers = vec![ProviderSelection::exact(
        Provider::Google,
        ProviderRequestProfile::new(policy.page.clone(), policy.request, policy.documents)?,
    )];
    let request_error = ys::request::new("http://127.0.0.1:1/")
        .bind(&policy)
        .send()
        .await
        .err()
        .ok_or("request should fail before dispatch")?;
    assert!(
        matches!(request_error.respectfulness(), Some(ys::policy::respectfulness::RespectfulnessError::Registry { variant, .. }) if variant == "InvalidState")
    );
    let search_error = ys::search::new("offline registry check")?
        .bind(&policy)
        .send()
        .await
        .err()
        .ok_or("search should fail before provider work")?;
    assert!(
        matches!(search_error, ys::search::SearchSendError::Respectfulness(ys::policy::respectfulness::RespectfulnessError::Registry { variant, .. }) if variant == "InvalidState")
    );
    let registry = Registry::jsonl(directory.path().join("override.jsonl"))?;
    let response = ys::request::new("http://127.0.0.1:1/")
        .bind(&policy)
        .with_registry(&registry)
        .send()
        .await?;
    assert!(
        response
            .respectfulness()
            .iter()
            .any(|event| event.error.as_ref().is_some_and(|error| matches!(
                error,
                ys::policy::respectfulness::RespectfulnessError::Limited {
                    reason: ys::policy::respectfulness::LimitReason::Blocked,
                    ..
                }
            )))
    );
    Ok(())
}
