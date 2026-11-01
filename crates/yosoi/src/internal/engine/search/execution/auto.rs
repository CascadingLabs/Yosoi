//! Atomic rotation and first-request admission. No provider work runs here.
use super::super::AutoRotationTrace;
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
    task::{JoinHandle, spawn_blocking},
    time::{Instant, timeout_at},
};
use tokio_util::sync::CancellationToken;

#[derive(Default)]
pub(super) struct Choice {
    pub slot: Option<usize>,
    pub rotation: Option<AutoRotationTrace>,
    pub permit: Option<Permit>,
    pub rejected: Vec<(usize, RespectfulnessError)>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Cursor {
    next: u64,
    selected: Provider,
}

pub(super) struct RotationContext {
    pub request_id: String,
    pub policy_version: u16,
    pub policy_sha256: String,
}

pub(super) async fn select(
    providers: Vec<Provider>,
    targets: Vec<Option<String>>,
    policy: Option<Respectfulness>,
    registry: Registry,
    cancellation: &CancellationToken,
    deadline: Instant,
    context: RotationContext,
) -> Result<Choice, RespectfulnessError> {
    if cancellation.is_cancelled() || Instant::now() >= deadline {
        return Ok(Choice::default());
    }
    let token = cancellation.clone();
    let task = spawn_blocking(move || {
        select_traced_at(
            &providers, &targets, policy, &registry, &token, deadline, &context,
        )
    });
    settle_selection(task, cancellation, deadline).await
}

async fn settle_selection(
    mut task: JoinHandle<Result<Choice, RespectfulnessError>>,
    cancellation: &CancellationToken,
    deadline: Instant,
) -> Result<Choice, RespectfulnessError> {
    let result = tokio::select! {
        biased;
        result = &mut task => result,
        () = cancellation.cancelled() => { task.abort(); task.await },
        _ = timeout_at(deadline, pending::<()>()) => { task.abort(); task.await },
    };
    match result {
        Ok(choice) => choice,
        Err(error) if error.is_cancelled() => Ok(Choice::default()),
        Err(_) => Err(RespectfulnessError::Setup {
            message: "Auto selection task failed".to_owned(),
        }),
    }
}

fn select_traced_at(
    providers: &[Provider],
    targets: &[Option<String>],
    policy: Option<Respectfulness>,
    registry: &Registry,
    cancellation: &CancellationToken,
    deadline: Instant,
    context: &RotationContext,
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
        let cursor_before = snapshot
            .entries
            .get(&key)
            .map(|value| serde_json::from_value::<Cursor>(value.clone()).map(|cursor| cursor.next))
            .transpose()
            .map_err(|_| RespectfulnessError::InvalidState)?;
        let mut index = usize::try_from(cursor_before.unwrap_or(0))
            .map_err(|_| RespectfulnessError::InvalidState)?;
        if index >= providers.len() {
            return Err(RespectfulnessError::InvalidState);
        }
        let mut choice = Choice {
            rotation: Some(AutoRotationTrace {
                schema_version: 1,
                search_request_id: context.request_id.clone(),
                policy_identity_version: context.policy_version,
                policy_identity_sha256: context.policy_sha256.clone(),
                candidates: providers.to_vec(),
                registry_key: key.clone(),
                cursor_before,
                cursor_after: cursor_before,
                revision_before: snapshot.revision.clone(),
                revision_after: snapshot.revision.clone(),
                transaction: None,
                selected_provider: None,
                skipped: Vec::new(),
                request_ids: Vec::new(),
            }),
            ..Choice::default()
        };
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
            context.resources.push(format!(
                "search/request/{}",
                choice
                    .rotation
                    .as_ref()
                    .ok_or(RespectfulnessError::InvalidState)?
                    .search_request_id
            ));
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
            match registry.commit_with_receipt(&snapshot.revision, &changes, &context) {
                Ok((committed, transaction)) => {
                    let rotation = choice
                        .rotation
                        .as_mut()
                        .ok_or(RespectfulnessError::InvalidState)?;
                    rotation.cursor_after =
                        Some(u64::try_from(index).map_err(|_| RespectfulnessError::InvalidState)?);
                    rotation.revision_after = committed.revision;
                    rotation.transaction =
                        Some(transaction.ok_or(RespectfulnessError::InvalidState)?);
                    rotation.selected_provider = Some(provider);
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
    use std::{error::Error, io, sync::mpsc, time::Duration};
    use tokio::sync::oneshot;

    fn select_at(
        providers: &[Provider],
        targets: &[Option<String>],
        policy: Option<Respectfulness>,
        registry: &Registry,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<Choice, RespectfulnessError> {
        use uuid::Uuid;
        select_traced_at(
            providers,
            targets,
            policy,
            registry,
            cancellation,
            deadline,
            &RotationContext {
                request_id: Uuid::new_v4().to_string(),
                policy_version: 10,
                policy_sha256: "0".repeat(64),
            },
        )
    }

    type TestResult = Result<(), Box<dyn Error>>;

    #[tokio::test]
    async fn cancellation_settles_an_already_running_selection() -> TestResult {
        let (started_tx, started_rx) = oneshot::channel();
        let (release_tx, release_rx) = mpsc::channel();
        let task = spawn_blocking(move || {
            let _ = started_tx.send(());
            release_rx
                .recv()
                .map_err(|_| RespectfulnessError::InvalidState)?;
            Ok(Choice {
                slot: Some(0),
                ..Choice::default()
            })
        });
        started_rx.await?;
        let token = CancellationToken::new();
        token.cancel();
        release_tx.send(())?;
        let deadline = Instant::now()
            .checked_add(Duration::from_secs(5))
            .ok_or("deadline")?;
        assert_eq!(
            settle_selection(task, &token, deadline).await?.slot,
            Some(0)
        );
        Ok(())
    }

    #[tokio::test]
    async fn unused_prepaid_permit_is_released_without_refunding_start() -> TestResult {
        let directory = tempfile::tempdir()?;
        let registry = Registry::jsonl(directory.path().join("unused.jsonl"))?;
        let target = "https://example.com/search".to_owned();
        let policy = Respectfulness::new(vec![Group {
            concurrency: Some(1),
            budgets: vec![RateBudget {
                requests: 2,
                window_ms: 60_000,
            }],
            ..Group::new("shared", ["^https://example\\.com/"])
        }])?;
        let deadline = Instant::now()
            .checked_add(Duration::from_secs(5))
            .ok_or("deadline")?;
        let providers = [Provider::Bing];
        let targets = [Some(target.clone())];
        let mut first = select_at(
            &providers,
            &targets,
            Some(policy.clone()),
            &registry,
            &CancellationToken::new(),
            deadline,
        )?;
        let operation = Operation::from_permit(first.permit.take().ok_or("permit")?, target);
        operation.finish().await?;
        let mut second = select_at(
            &providers,
            &targets,
            Some(policy.clone()),
            &registry,
            &CancellationToken::new(),
            deadline,
        )?;
        assert_eq!(second.slot, Some(0));
        Operation::from_permit(
            second.permit.take().ok_or("permit")?,
            "https://example.com/search".to_owned(),
        )
        .finish()
        .await?;
        let third = select_at(
            &providers,
            &targets,
            Some(policy),
            &registry,
            &CancellationToken::new(),
            deadline,
        )?;
        assert!(third.slot.is_none());
        Ok(())
    }

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
        let mut rotation = None;
        assert_eq!(
            route_jobs(
                &prepared,
                &mut jobs,
                &mut slots,
                &cancellation,
                deadline,
                &mut rotation
            )
            .await?,
            Some(Provider::Bing)
        );
        assert_eq!(jobs.len(), 1);
        let job = jobs.pop_front().ok_or("selected job")?;
        let result = timeout(
            Duration::from_secs(3),
            execute_provider(job.payload, &cancellation, true),
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
        #[cfg(unix)]
        {
            use super::super::finish_rotation;
            use crate::policy::search::Routing;
            use crate::{
                Archive,
                search::{AutoRotationTrace, SearchReplayError, SearchResponse, SearchTermination},
            };
            use std::{fs, slice};
            finish_rotation(&mut rotation, slice::from_ref(&result))?;
            let response = SearchResponse {
                rotation,
                routing: Routing::Auto,
                selected_provider: Some(Provider::Bing),
                request_id: prepared.request_id(),
                policy_identity: prepared.policy_snapshot().identity(),
                providers: vec![result],
                termination: SearchTermination::Completed,
            };
            let archive = Archive::open(directory.path().join("archive")).await?;
            let evidence = response.save_diagnostics(&archive).await?;
            let reference = evidence.rotation.ok_or("rotation reference")?;
            assert_eq!(evidence.records.len(), 1);
            let mut record = evidence.records.into_iter().next().ok_or("capture")?;
            assert_eq!(record.rotation.as_ref(), Some(&reference));
            let before = registry.snapshot()?;
            registry.compact()?;
            assert_eq!(registry.snapshot()?, before);
            let path = registry.path().to_owned();
            fs::rename(&path, directory.path().join("registry-offline.jsonl"))?;
            let restored = AutoRotationTrace::read_from(&archive, &reference).await?;
            assert_eq!(Some(&restored), response.rotation());
            assert_eq!(
                record.replay(&archive).await?.decision().failure,
                Some(SearchFailure::RateLimited)
            );
            assert!(
                !path.exists(),
                "replay must not initialize or consult Registry"
            );
            record.request_id = restored.search_request_id;
            assert!(matches!(
                record.replay(&archive).await,
                Err(SearchReplayError::InvalidBounds)
            ));
        }
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

    #[cfg(unix)]
    #[tokio::test(flavor = "current_thread")]
    async fn committed_rotation_links_exact_journal_receipt_and_survives_compaction() -> TestResult
    {
        use crate::{Archive, search::AutoRotationTrace};
        use std::fs;
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("receipt.jsonl");
        let registry = Registry::jsonl(&path)?;
        let choice = select_at(
            &[Provider::Bing, Provider::Brave],
            &[
                Some("https://example.com/".to_owned()),
                Some("https://example.com/".to_owned()),
            ],
            None,
            &registry,
            &CancellationToken::new(),
            Instant::now()
                .checked_add(Duration::from_secs(2))
                .ok_or("deadline")?,
        )?;
        let trace = choice.rotation.ok_or("trace")?;
        let receipt = trace.transaction.as_ref().ok_or("receipt")?;
        let journal = fs::read_to_string(&path)?;
        let row: serde_json::Value =
            serde_json::from_str(journal.lines().nth(1).ok_or("commit line")?)?;
        assert_eq!(
            serde_json::to_value(receipt)?,
            *row.get("transaction").ok_or("envelope")?
        );
        assert_eq!(trace.cursor_before, None);
        assert_eq!(trace.cursor_after, Some(1));
        assert_eq!(trace.revision_before.sequence, 0);
        assert_eq!(trace.revision_after.sequence, 1);
        assert_eq!(receipt.caller, *registry.caller());
        assert!(
            receipt
                .context
                .resources
                .contains(&format!("search/request/{}", trace.search_request_id))
        );
        assert!(trace.validate());
        let archive = Archive::open(directory.path().join("archive")).await?;
        let reference = trace.write_to(&archive).await?;
        let before = registry.snapshot()?;
        registry.compact()?;
        assert_eq!(registry.snapshot()?, before);
        assert_eq!(
            AutoRotationTrace::read_from(&archive, &reference).await?,
            trace
        );
        let mut invalid = trace;
        invalid.transaction.as_mut().ok_or("receipt")?.sequence = 99;
        assert!(invalid.write_to(&archive).await.is_err());
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
