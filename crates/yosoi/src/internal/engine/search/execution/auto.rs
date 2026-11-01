//! Atomic rotation and first-request admission. No provider work runs here.
use crate::{
    internal::{
        respectfulness::{Permit, Runtime, expiry, now_ms},
        types::Sha256Digest,
    },
    policy::{
        respectfulness::{Respectfulness, RespectfulnessError},
        search::Provider,
    },
    registry::{Change, Registry, RegistryError, TransactionContext},
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::future::pending;
use tokio::{
    task::spawn_blocking,
    time::{Instant, timeout_at},
};
use tokio_util::sync::CancellationToken;

#[derive(Default)]
pub(super) struct Choice {
    pub slot: Option<usize>,
    pub permit: Option<Permit>,
    pub rejected: Vec<(usize, RespectfulnessError)>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Cursor {
    next: u64,
    selected: Provider,
}

pub(super) async fn select(
    providers: Vec<Provider>,
    targets: Vec<Option<String>>,
    policy: Option<Respectfulness>,
    registry: Registry,
    cancellation: &CancellationToken,
    deadline: Instant,
) -> Result<Choice, RespectfulnessError> {
    if cancellation.is_cancelled() || Instant::now() >= deadline {
        return Ok(Choice::default());
    }
    let token = cancellation.clone();
    let mut task = spawn_blocking(move || {
        select_at(&providers, &targets, policy, &registry, &token, deadline)
    });
    tokio::select! {
        biased;
        () = cancellation.cancelled() => { task.abort(); Ok(Choice::default()) },
        _ = timeout_at(deadline, pending::<()>()) => { task.abort(); Ok(Choice::default()) },
        result = &mut task => result.map_err(|_| RespectfulnessError::Setup {message:"Auto selection task failed".to_owned()})?,
    }
}

fn select_at(
    providers: &[Provider],
    targets: &[Option<String>],
    policy: Option<Respectfulness>,
    registry: &Registry,
    cancellation: &CancellationToken,
    deadline: Instant,
) -> Result<Choice, RespectfulnessError> {
    if providers.is_empty() || targets.len() != providers.len() {
        return Err(RespectfulnessError::InvalidState);
    }
    let encoded = serde_json::to_vec(providers).map_err(|_| RespectfulnessError::InvalidState)?;
    let digest = Sha256Digest::from_bytes(Sha256::digest(encoded).into());
    let key = format!("search/auto/v1/{digest}");
    let runtime = policy
        .map(|policy| Runtime::new(policy, registry.clone()))
        .transpose()?;
    for _ in 0..8 {
        if cancellation.is_cancelled() || Instant::now() >= deadline {
            return Ok(Choice::default());
        }
        let snapshot = registry.snapshot()?;
        let mut index = match snapshot.entries.get(&key) {
            Some(value) => usize::try_from(
                serde_json::from_value::<Cursor>(value.clone())
                    .map_err(|_| RespectfulnessError::InvalidState)?
                    .next,
            )
            .map_err(|_| RespectfulnessError::InvalidState)?,
            None => 0,
        };
        if index >= providers.len() {
            return Err(RespectfulnessError::InvalidState);
        }
        let mut choice = Choice::default();
        let mut conflict = false;
        for _ in 0..providers.len() {
            let slot = index;
            index = index
                .checked_add(1)
                .filter(|next| *next < providers.len())
                .unwrap_or(0);
            let Some(target) = targets.get(slot).and_then(Option::as_ref) else {
                continue;
            };
            let now = now_ms()?;
            let until = expiry(now, deadline.saturating_duration_since(Instant::now()))?;
            let plan = match runtime
                .as_ref()
                .map(|runtime| runtime.plan_at(&snapshot, target, now, until))
                .transpose()
            {
                Ok(plan) => plan,
                Err(
                    error @ (RespectfulnessError::Limited { .. } | RespectfulnessError::Unmatched),
                ) => {
                    choice.rejected.push((slot, error));
                    continue;
                }
                Err(error) => return Err(error),
            };
            let (mut changes, mut context, permit) = plan.map_or_else(
                || (Vec::new(), TransactionContext::default(), None),
                |plan| (plan.changes, plan.context, Some(plan.permit)),
            );
            "search.auto.select".clone_into(&mut context.operation);
            context.resources.push(key.clone());
            let provider = providers
                .get(slot)
                .copied()
                .ok_or(RespectfulnessError::InvalidState)?;
            changes.push(Change::Put {
                key: key.clone(),
                value: serde_json::to_value(Cursor {
                    next: u64::try_from(index).map_err(|_| RespectfulnessError::InvalidState)?,
                    selected: provider,
                })
                .map_err(|_| RespectfulnessError::InvalidState)?,
            });
            if cancellation.is_cancelled() || Instant::now() >= deadline {
                return Ok(Choice::default());
            }
            match registry.commit_with_context(&snapshot.revision, &changes, &context) {
                Ok(_) => {
                    choice.slot = Some(slot);
                    choice.permit = permit;
                    return Ok(choice);
                }
                Err(RegistryError::Conflict) => {
                    conflict = true;
                    break;
                }
                Err(error) => return Err(error.into()),
            }
        }
        if !conflict {
            return Ok(choice);
        }
    }
    Err(RespectfulnessError::Setup {
        message: "Auto selection contention exceeded its reevaluation budget".to_owned(),
    })
}

#[cfg(test)]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions describe selection and admission invariants."
)]
mod tests {
    use super::*;
    use crate::policy::respectfulness::EventKind;
    use crate::{
        internal::respectfulness::Operation,
        policy::respectfulness::{Group, RateBudget},
    };
    use std::{error::Error, io, time::Duration};

    type TestResult = Result<(), Box<dyn Error>>;

    #[test]
    fn rotation_wraps_and_survives_independent_handles_and_restart() -> TestResult {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("rotation.jsonl");
        let providers = [
            Provider::Google,
            Provider::DuckDuckGo,
            Provider::Bing,
            Provider::Brave,
        ];
        let targets = providers
            .iter()
            .map(|_| Some("https://example.com/search".to_owned()))
            .collect::<Vec<_>>();
        for expected in [0, 1, 2, 3, 0, 1] {
            let registry = Registry::jsonl(&path)?;
            let choice = select_at(
                &providers,
                &targets,
                None,
                &registry,
                &CancellationToken::new(),
                Instant::now()
                    .checked_add(Duration::from_secs(2))
                    .ok_or("deadline")?,
            )?;
            assert_eq!(choice.slot, Some(expected));
            assert!(choice.permit.is_none());
        }
        assert_eq!(Registry::jsonl(path)?.snapshot()?.revision.sequence, 6);
        Ok(())
    }

    #[tokio::test(flavor = "current_thread")]
    async fn cursor_and_admission_commit_together_and_first_send_is_not_charged_twice() -> TestResult
    {
        let directory = tempfile::tempdir()?;
        let registry = Registry::jsonl(directory.path().join("atomic.jsonl"))?;
        let providers = [Provider::Bing, Provider::Brave];
        let targets = vec![
            Some("https://example.com/bing".to_owned()),
            Some("https://example.com/brave".to_owned()),
        ];
        let policy = Respectfulness::new(vec![Group {
            concurrency: Some(1),
            budgets: vec![RateBudget {
                requests: 1,
                window_ms: 60_000,
            }],
            ..Group::new("shared", ["^https://example\\.com/"])
        }])?;
        let deadline = Instant::now()
            .checked_add(Duration::from_secs(2))
            .ok_or("deadline")?;
        let mut choice = select_at(
            &providers,
            &targets,
            Some(policy.clone()),
            &registry,
            &CancellationToken::new(),
            deadline,
        )?;
        assert_eq!(choice.slot, Some(0));
        let committed = registry.snapshot()?;
        assert_eq!(committed.revision.sequence, 1);
        assert_eq!(committed.entries.len(), 2);
        let target = targets
            .first()
            .and_then(Option::as_ref)
            .ok_or("target")?
            .clone();
        let operation =
            Operation::from_permit(choice.permit.take().ok_or("permit")?, target.clone());
        operation.acquire(target, Duration::from_secs(2)).await?;
        assert_eq!(registry.snapshot()?, committed);
        operation.finish().await?;
        let released = registry.snapshot()?;
        let choice = select_at(
            &providers,
            &targets,
            Some(policy),
            &registry,
            &CancellationToken::new(),
            deadline,
        )?;
        assert!(choice.slot.is_none());
        assert_eq!(choice.rejected.len(), 2);
        assert_eq!(registry.snapshot()?, released);
        Ok(())
    }

    #[test]
    fn unsupported_and_blocked_candidates_do_not_advance_or_reserve() -> TestResult {
        let directory = tempfile::tempdir()?;
        let registry = Registry::jsonl(directory.path().join("blocked.jsonl"))?;
        let policy = Respectfulness::new(vec![Group {
            blocked: true,
            ..Group::new("blocked", ["^https://"])
        }])?;
        let original = registry.snapshot()?;
        let choice = select_at(
            &[Provider::Google, Provider::Bing],
            &[None, Some("https://example.com/".to_owned())],
            Some(policy),
            &registry,
            &CancellationToken::new(),
            Instant::now()
                .checked_add(Duration::from_secs(2))
                .ok_or("deadline")?,
        )?;
        assert!(choice.slot.is_none());
        assert_eq!(choice.rejected.len(), 1);
        assert_eq!(registry.snapshot()?, original);
        Ok(())
    }
    #[tokio::test(flavor = "current_thread")]
    async fn admitted_request_sends_once_and_does_not_fall_back_after_429() -> TestResult {
        use crate::{internal::engine::request::new as new_request, policy::Policy};
        use tokio::{
            io::{AsyncReadExt, AsyncWriteExt},
            net::TcpListener,
            time::timeout,
        };
        let first = TcpListener::bind("127.0.0.1:0").await?;
        let other = TcpListener::bind("127.0.0.1:0").await?;
        let target = format!("http://{}/", first.local_addr()?);
        let unused = format!("http://{}/", other.local_addr()?);
        let server = tokio::spawn(async move {
            let (mut stream, _) = first.accept().await?;
            let mut head = Vec::new();
            let mut byte = [0_u8];
            while !head.ends_with(b"\r\n\r\n") {
                stream.read_exact(&mut byte).await?;
                head.extend_from_slice(&byte);
                if head.len() > 8192 {
                    return Err(io::Error::other("oversized request"));
                }
            }
            stream.write_all(b"HTTP/1.1 429 Too Many Requests\r\nContent-Type: text/plain\r\nContent-Length: 7\r\nConnection: close\r\n\r\nlimited").await?;
            Ok::<_, io::Error>(())
        });
        let directory = tempfile::tempdir()?;
        let registry = Registry::jsonl(directory.path().join("request.jsonl"))?;
        let respect = Respectfulness::new(vec![Group {
            concurrency: Some(1),
            budgets: vec![RateBudget {
                requests: 1,
                window_ms: 60_000,
            }],
            ..Group::new("request", ["^http://"])
        }])?;
        use super::super::{ScheduledJob, execute_provider, prepare_provider_job, route_jobs};
        use crate::{
            internal::{
                engine::search::{ProviderOutcome, SearchFailure, new as new_search},
                web_capture::RequestedWebTarget,
            },
            policy::{
                AddressableByteLimit,
                search::{ProfileSelection, ProviderRequestProfile, Search},
            },
        };
        use std::collections::VecDeque;
        let mut policy = Policy {
            respectfulness: Some(respect),
            search: Search::auto([Provider::Bing, Provider::Brave])?,
            ..Policy::default()
        };
        let profile =
            ProviderRequestProfile::new(policy.page.clone(), policy.request, policy.documents)?;
        for candidate in &mut policy.search.providers {
            candidate.profile = ProfileSelection::Exact(profile.clone());
        }
        let prepared = new_search("loopback auto")?
            .bind(&policy)
            .with_registry(&registry)
            .prepare()?;
        let mut jobs = VecDeque::new();
        let mut slots = Vec::new();
        for (slot, route) in prepared.providers().iter().enumerate() {
            let (prebuilt, job) = prepare_provider_job(
                &prepared,
                route,
                AddressableByteLimit::try_from(4096_u64)?,
                4096,
                5,
            )?;
            slots.push(prebuilt);
            let mut job = job.ok_or("supported loopback job")?;
            let target = if slot == 0 { &target } else { &unused };
            job.provider_target = RequestedWebTarget::parse(target)?;
            job.request = new_request(target);
            jobs.push_back(ScheduledJob {
                slot,
                uses_browser: false,
                payload: job,
            });
        }
        let cancellation = CancellationToken::new();
        let deadline = Instant::now()
            .checked_add(Duration::from_secs(3))
            .ok_or("deadline")?;
        assert_eq!(
            route_jobs(&prepared, &mut jobs, &mut slots, &cancellation, deadline).await?,
            Some(Provider::Bing)
        );
        assert_eq!(jobs.len(), 1);
        let job = jobs.pop_front().ok_or("selected job")?;
        let result = timeout(
            Duration::from_secs(3),
            execute_provider(job.payload, &cancellation, false),
        )
        .await?;
        assert!(matches!(
            result.outcome(),
            ProviderOutcome::Failed(SearchFailure::RateLimited)
        ));
        assert_eq!(
            result
                .attempts()
                .first()
                .and_then(|attempt| attempt.http_status),
            Some(429)
        );
        assert_eq!(
            result
                .respectfulness()
                .iter()
                .filter(|event| event.kind == EventKind::Admitted)
                .count(),
            1
        );
        server.await??;
        assert!(
            timeout(Duration::from_millis(10), other.accept())
                .await
                .is_err()
        );
        Ok(())
    }
    #[test]
    fn independent_processes_share_rotation_without_duplicate_turns() -> TestResult {
        use std::{
            env,
            io::{BufRead, BufReader, Read, Write},
            process::{Command, Stdio},
        };
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("processes.jsonl");
        let registry = Registry::jsonl(&path)?;
        let mut children = Vec::new();
        for _ in 0..2 {
            let mut child = Command::new(env::current_exe()?)
                .args([
                    "--exact",
                    "internal::engine::search::execution::auto::tests::child_rotation",
                    "--ignored",
                    "--nocapture",
                ])
                .env("YOSOI_AUTO_TEST_JOURNAL", &path)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .spawn()?;
            let mut output = BufReader::new(child.stdout.take().ok_or("stdout")?);
            let mut line = String::new();
            loop {
                if output.read_line(&mut line)? == 0 {
                    return Err("child exited before readiness".into());
                }
                if line.contains("AUTO_READY") {
                    break;
                }
                line.clear();
            }
            children.push((child, output));
        }
        for (child, _) in &mut children {
            child.stdin.take().ok_or("stdin")?.write_all(b"x")?;
        }
        let mut seen = Vec::new();
        for (mut child, mut output) in children {
            let mut text = String::new();
            output.read_to_string(&mut text)?;
            assert!(child.wait()?.success(), "{text}");
            for line in text.lines() {
                if let Some((_, value)) = line.split_once("AUTO_SELECTED:") {
                    seen.push(value.trim().parse::<usize>()?);
                }
            }
        }
        let count = seen.len();
        assert!(count > 0);
        seen.sort_unstable();
        seen.dedup();
        assert_eq!(seen, (0..count).collect::<Vec<_>>());
        assert_eq!(
            registry.snapshot()?.revision.sequence,
            u64::try_from(count)?
        );
        let reopened = Registry::jsonl(&path)?;
        let choice = select_at(
            &[Provider::Bing, Provider::Brave, Provider::Google],
            &vec![Some("https://example.com/".to_owned()); 3],
            None,
            &reopened,
            &CancellationToken::new(),
            Instant::now()
                .checked_add(Duration::from_secs(2))
                .ok_or("deadline")?,
        )?;
        assert_eq!(choice.slot, Some(count));
        Ok(())
    }

    #[test]
    #[ignore = "subprocess helper invoked by the independent-process test"]
    fn child_rotation() -> TestResult {
        use std::{
            env,
            io::{self, Read, Write},
        };
        let registry = Registry::jsonl(env::var_os("YOSOI_AUTO_TEST_JOURNAL").ok_or("journal")?)?;
        println!("AUTO_READY");
        io::stdout().flush()?;
        let mut gate = [0_u8];
        io::stdin().read_exact(&mut gate)?;
        match select_at(
            &[Provider::Bing, Provider::Brave, Provider::Google],
            &vec![Some("https://example.com/".to_owned()); 3],
            None,
            &registry,
            &CancellationToken::new(),
            Instant::now()
                .checked_add(Duration::from_secs(2))
                .ok_or("deadline")?,
        ) {
            Ok(choice) => println!("AUTO_SELECTED:{}", choice.slot.ok_or("selection")?),
            Err(RespectfulnessError::Registry { variant, .. }) if variant == "Busy" => {
                println!("AUTO_BUSY");
            }
            Err(error) => return Err(error.into()),
        }
        Ok(())
    }
}
