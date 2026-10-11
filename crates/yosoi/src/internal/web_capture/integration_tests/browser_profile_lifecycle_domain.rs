#![allow(
    clippy::panic_in_result_fn,
    reason = "test assertions provide clearer lifecycle transition diagnostics"
)]

use std::{collections::BTreeMap, error::Error, fs, num::NonZeroU64};

use crate::internal::web_capture::{
    BrowserProfileId, BrowserProfileLeaseGeneration, BrowserProfileLifecycleError,
    BrowserProfileLifecycleEvent as Event, BrowserProfileLifecycleReason as Reason,
    BrowserProfileLifecycleRecord, BrowserProfileLifecycleSource as Source,
    BrowserProfileLifecycleState as State, BrowserProfilePoolSnapshot,
    BrowserProfileQuarantineReason as QuarantineReason, MAX_BROWSER_PROFILE_POOL_SNAPSHOT_ENTRIES,
    ProfileLifecycleStore, ProfileLifecycleStoreError, classify_abandoned_on_startup,
    reduce_browser_profile_lifecycle,
};
use chrono::{DateTime, Utc};

fn generation(value: u64) -> Result<BrowserProfileLeaseGeneration, Box<dyn Error>> {
    let value = NonZeroU64::new(value).ok_or("generation must be nonzero")?;
    Ok(BrowserProfileLeaseGeneration::new(value))
}

fn observed_at() -> Result<DateTime<Utc>, Box<dyn Error>> {
    DateTime::parse_from_rfc3339("2026-09-24T12:00:00Z")
        .map(|value| value.with_timezone(&Utc))
        .map_err(Into::into)
}

fn reduce_state(
    state: State,
    latest_generation: Option<BrowserProfileLeaseGeneration>,
    event: Event,
) -> Result<State, BrowserProfileLifecycleError> {
    let transition = reduce_browser_profile_lifecycle(state, latest_generation, event)?;
    Ok(transition.next())
}

#[test]
fn only_available_profiles_are_eligible_and_events_move_through_expected_states()
-> Result<(), Box<dyn Error>> {
    let staged = State::Staged;
    assert!(!staged.is_eligible());
    let available = reduce_state(staged, None, Event::ProvisionSucceeded)?;
    assert_eq!(available, State::Available);
    assert!(available.is_eligible());

    let generation = generation(7)?;
    let leased_transition =
        reduce_browser_profile_lifecycle(available, None, Event::LeaseAcquired { generation })?;
    assert_eq!(leased_transition.next(), State::Leased { generation });
    assert_eq!(leased_transition.latest_generation(), Some(generation));
    assert!(!leased_transition.next().is_eligible());

    let released = reduce_browser_profile_lifecycle(
        leased_transition.next(),
        Some(generation),
        Event::LeaseReleased { generation },
    )?;
    assert_eq!(released.next(), State::Available);
    assert_eq!(released.latest_generation(), Some(generation));
    assert!(released.next().is_eligible());
    Ok(())
}

#[test]
fn reducer_rejects_invalid_and_stale_lease_transitions() -> Result<(), Box<dyn Error>> {
    assert_eq!(
        reduce_state(
            State::Staged,
            None,
            Event::LeaseAcquired {
                generation: generation(2)?,
            }
        ),
        Err(BrowserProfileLifecycleError::InvalidTransition)
    );

    let leased = State::Leased {
        generation: generation(3)?,
    };
    assert_eq!(
        reduce_state(
            leased,
            Some(generation(3)?),
            Event::LeaseReleased {
                generation: generation(2)?,
            }
        ),
        Err(BrowserProfileLifecycleError::StaleGeneration)
    );
    assert_eq!(
        reduce_state(
            leased,
            Some(generation(3)?),
            Event::LeaseAcquired {
                generation: generation(2)?,
            }
        ),
        Err(BrowserProfileLifecycleError::StaleGeneration)
    );
    Ok(())
}

#[test]
fn released_generation_remains_fenced_while_profile_is_available() -> Result<(), Box<dyn Error>> {
    let generation_seven = generation(7)?;
    let released = reduce_browser_profile_lifecycle(
        State::Leased {
            generation: generation_seven,
        },
        Some(generation_seven),
        Event::LeaseReleased {
            generation: generation_seven,
        },
    )?;
    assert_eq!(released.next(), State::Available);
    assert_eq!(released.latest_generation(), Some(generation_seven));
    assert_eq!(
        reduce_browser_profile_lifecycle(
            released.next(),
            released.latest_generation(),
            Event::LeaseAcquired {
                generation: generation(1)?,
            }
        ),
        Err(BrowserProfileLifecycleError::StaleGeneration)
    );

    let accepted = reduce_browser_profile_lifecycle(
        released.next(),
        released.latest_generation(),
        Event::LeaseAcquired {
            generation: generation(8)?,
        },
    )?;
    assert_eq!(
        accepted.next(),
        State::Leased {
            generation: generation(8)?,
        }
    );
    assert_eq!(accepted.latest_generation(), Some(generation(8)?));
    Ok(())
}

#[test]
fn generation_watermark_survives_quarantine_and_operator_review() -> Result<(), Box<dyn Error>> {
    let generation_seven = generation(7)?;
    let quarantined = reduce_browser_profile_lifecycle(
        State::Leased {
            generation: generation_seven,
        },
        Some(generation_seven),
        Event::LeaseOwnershipUncertain {
            generation: generation_seven,
        },
    )?;
    assert_eq!(quarantined.latest_generation(), Some(generation_seven));

    let reviewed = reduce_browser_profile_lifecycle(
        quarantined.next(),
        quarantined.latest_generation(),
        Event::OperatorReviewApproved,
    )?;
    assert_eq!(reviewed.next(), State::Available);
    assert_eq!(reviewed.latest_generation(), Some(generation_seven));
    assert_eq!(
        reduce_browser_profile_lifecycle(
            reviewed.next(),
            reviewed.latest_generation(),
            Event::LeaseAcquired {
                generation: generation(1)?,
            }
        ),
        Err(BrowserProfileLifecycleError::StaleGeneration)
    );
    Ok(())
}

#[test]
fn uncertain_expiry_and_startup_states_fail_closed() -> Result<(), Box<dyn Error>> {
    let expired = reduce_state(
        State::Leased {
            generation: generation(5)?,
        },
        Some(generation(5)?),
        Event::LeaseExpired {
            generation: generation(5)?,
        },
    )?;
    assert_eq!(
        expired,
        State::Quarantined {
            reason: QuarantineReason::LeaseExpired,
        }
    );
    assert!(!expired.is_eligible());

    assert_eq!(
        classify_abandoned_on_startup(State::Staged),
        State::Quarantined {
            reason: QuarantineReason::StartupProvisionInterrupted,
        }
    );
    assert_eq!(
        classify_abandoned_on_startup(State::Leased {
            generation: generation(9)?,
        }),
        State::Quarantined {
            reason: QuarantineReason::StartupLeaseInterrupted,
        }
    );
    assert_eq!(
        classify_abandoned_on_startup(State::Available),
        State::Available
    );
    assert_eq!(
        classify_abandoned_on_startup(expired),
        expired,
        "startup classification does not recover quarantined state"
    );
    Ok(())
}

#[test]
fn fork_uncertainty_and_lease_ownership_uncertainty_quarantine() -> Result<(), Box<dyn Error>> {
    assert_eq!(
        reduce_state(State::Staged, None, Event::ForkChildAvailable)?,
        State::Available
    );
    assert_eq!(
        reduce_state(State::Staged, None, Event::ForkChildUncertain)?,
        State::Quarantined {
            reason: QuarantineReason::ForkOutcomeUncertain,
        }
    );

    let generation = generation(11)?;
    let uncertain = reduce_state(
        State::Leased { generation },
        Some(generation),
        Event::LeaseOwnershipUncertain { generation },
    )?;
    assert_eq!(
        uncertain,
        State::Quarantined {
            reason: QuarantineReason::LeaseOwnershipUncertain,
        }
    );

    let retired = reduce_state(uncertain, Some(generation), Event::OperatorRetire)?;
    assert_eq!(retired, State::Retired);
    assert_eq!(
        reduce_state(retired, Some(generation), Event::OperatorReviewApproved),
        Err(BrowserProfileLifecycleError::InvalidTransition)
    );
    Ok(())
}

#[test]
fn transition_record_is_validated_secret_safe_and_round_trips() -> Result<(), Box<dyn Error>> {
    let record = BrowserProfileLifecycleRecord::from_event(
        observed_at()?,
        State::Available,
        None,
        Event::LeaseAcquired {
            generation: generation(4)?,
        },
    )?;
    assert_eq!(record.source(), Source::LeaseManager);
    assert_eq!(record.reason(), Reason::LeaseAcquired);
    assert_eq!(record.schema_version(), 2);
    assert_eq!(record.latest_generation(), Some(generation(4)?));

    let encoded = serde_json::to_string(&record)?;
    assert!(!encoded.contains("/home/"));
    assert!(!encoded.contains("https://"));
    assert_eq!(
        serde_json::from_str::<BrowserProfileLifecycleRecord>(&encoded)?,
        record
    );

    let mut unsupported: serde_json::Value = serde_json::from_str(&encoded)?;
    unsupported["schema_version"] = serde_json::json!(3);
    assert!(serde_json::from_value::<BrowserProfileLifecycleRecord>(unsupported).is_err());

    let mut inconsistent_watermark: serde_json::Value = serde_json::from_str(&encoded)?;
    inconsistent_watermark["latest_generation"] = serde_json::json!(3);
    assert!(
        serde_json::from_value::<BrowserProfileLifecycleRecord>(inconsistent_watermark).is_err()
    );

    let invalid = BrowserProfileLifecycleRecord::new(
        observed_at()?,
        Source::LeaseManager,
        State::Available,
        None,
        State::Available,
        None,
        Reason::LeaseAcquired,
    );
    assert_eq!(invalid, Err(BrowserProfileLifecycleError::InvalidRecord));
    Ok(())
}

#[test]
fn pool_snapshot_is_deterministic_and_bounded() -> Result<(), Box<dyn Error>> {
    let available = BrowserProfileLifecycleRecord::from_event(
        observed_at()?,
        State::Staged,
        None,
        Event::ProvisionSucceeded,
    )?;
    let mut records = BTreeMap::new();
    for index in 0..=MAX_BROWSER_PROFILE_POOL_SNAPSHOT_ENTRIES {
        let profile_id = BrowserProfileId::new(format!("profile-{index:03}"))?;
        records.insert(profile_id, available.clone());
    }

    let snapshot = BrowserProfilePoolSnapshot::from_records(&records);
    assert_eq!(
        snapshot.entries().len(),
        MAX_BROWSER_PROFILE_POOL_SNAPSHOT_ENTRIES
    );
    assert!(snapshot.is_truncated());
    assert_eq!(
        snapshot.eligible_count(),
        MAX_BROWSER_PROFILE_POOL_SNAPSHOT_ENTRIES
    );
    assert_eq!(
        snapshot
            .entries()
            .first()
            .map(|entry| entry.profile_id().as_str()),
        Some("profile-000")
    );
    Ok(())
}

#[test]
fn local_store_round_trips_valid_records_and_rejects_stale_commits() -> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let store = ProfileLifecycleStore::new(directory.path())?;
    let profile_id = BrowserProfileId::new("profile-store")?;

    let staged = store.stage_profile(&profile_id, observed_at()?)?;
    assert_eq!(staged.next(), State::Staged);

    let available = BrowserProfileLifecycleRecord::from_event(
        observed_at()?,
        State::Staged,
        None,
        Event::ProvisionSucceeded,
    )?;
    store.commit(&profile_id, &available)?;
    let loaded = store.load_all()?;
    assert_eq!(loaded.get(&profile_id), Some(&available));

    let stale = BrowserProfileLifecycleRecord::from_event(
        observed_at()?,
        State::Staged,
        None,
        Event::ProvisionSucceeded,
    )?;
    assert_eq!(
        store.commit(&profile_id, &stale),
        Err(ProfileLifecycleStoreError::StaleTransition)
    );
    Ok(())
}

#[test]
fn local_store_round_trip_preserves_generation_fence_after_release() -> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let store = ProfileLifecycleStore::new(directory.path())?;
    let profile_id = BrowserProfileId::new("profile-generation-fence")?;
    let generation_seven = generation(7)?;

    store.stage_profile(&profile_id, observed_at()?)?;
    let available = BrowserProfileLifecycleRecord::from_event(
        observed_at()?,
        State::Staged,
        None,
        Event::ProvisionSucceeded,
    )?;
    store.commit(&profile_id, &available)?;
    let leased = BrowserProfileLifecycleRecord::from_event(
        observed_at()?,
        State::Available,
        available.latest_generation(),
        Event::LeaseAcquired {
            generation: generation_seven,
        },
    )?;
    store.commit(&profile_id, &leased)?;
    let released = BrowserProfileLifecycleRecord::from_event(
        observed_at()?,
        leased.next(),
        leased.latest_generation(),
        Event::LeaseReleased {
            generation: generation_seven,
        },
    )?;
    store.commit(&profile_id, &released)?;

    let mut loaded = store.load_all()?;
    let reloaded = loaded
        .remove(&profile_id)
        .ok_or("released profile record is missing")?;
    assert_eq!(reloaded.next(), State::Available);
    assert_eq!(reloaded.latest_generation(), Some(generation_seven));
    let encoded = serde_json::to_string(&reloaded)?;
    let decoded: BrowserProfileLifecycleRecord = serde_json::from_str(&encoded)?;
    assert_eq!(decoded.latest_generation(), Some(generation_seven));

    assert_eq!(
        BrowserProfileLifecycleRecord::from_event(
            observed_at()?,
            decoded.next(),
            decoded.latest_generation(),
            Event::LeaseAcquired {
                generation: generation(1)?,
            },
        ),
        Err(BrowserProfileLifecycleError::StaleGeneration)
    );
    let next_lease = BrowserProfileLifecycleRecord::from_event(
        observed_at()?,
        decoded.next(),
        decoded.latest_generation(),
        Event::LeaseAcquired {
            generation: generation(8)?,
        },
    )?;
    store.commit(&profile_id, &next_lease)?;
    let mut loaded = store.load_all()?;
    let after_acquire = loaded
        .remove(&profile_id)
        .ok_or("new lease record is missing")?;
    assert_eq!(after_acquire.latest_generation(), Some(generation(8)?));
    assert_eq!(
        after_acquire.next(),
        State::Leased {
            generation: generation(8)?,
        }
    );
    Ok(())
}

#[test]
fn local_store_fails_closed_on_corrupt_records_without_echoing_contents()
-> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let store = ProfileLifecycleStore::new(directory.path())?;
    fs::write(
        directory.path().join("profile-corrupt.json"),
        br#"{"secret":"private-cookie-value"}"#,
    )?;

    let error = store
        .load_all()
        .err()
        .ok_or("corrupt record was unexpectedly accepted")?;
    assert_eq!(error, ProfileLifecycleStoreError::CorruptRecord);
    assert!(!error.to_string().contains("private-cookie-value"));
    Ok(())
}

#[test]
fn local_store_persists_startup_quarantine_without_recovery_or_deletion()
-> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let store = ProfileLifecycleStore::new(directory.path())?;
    let staged_id = BrowserProfileId::new("profile-staged")?;
    let leased_id = BrowserProfileId::new("profile-leased")?;
    let available_id = BrowserProfileId::new("profile-available")?;

    store.stage_profile(&staged_id, observed_at()?)?;

    store.stage_profile(&leased_id, observed_at()?)?;
    let available = BrowserProfileLifecycleRecord::from_event(
        observed_at()?,
        State::Staged,
        None,
        Event::ProvisionSucceeded,
    )?;
    store.commit(&leased_id, &available)?;
    let leased = BrowserProfileLifecycleRecord::from_event(
        observed_at()?,
        State::Available,
        None,
        Event::LeaseAcquired {
            generation: generation(6)?,
        },
    )?;
    store.commit(&leased_id, &leased)?;

    store.stage_profile(&available_id, observed_at()?)?;
    let ready = BrowserProfileLifecycleRecord::from_event(
        observed_at()?,
        State::Staged,
        None,
        Event::ProvisionSucceeded,
    )?;
    store.commit(&available_id, &ready)?;

    let changes = store.classify_abandoned_on_startup(observed_at()?)?;
    assert_eq!(changes.len(), 2);
    assert_eq!(
        store
            .load_all()?
            .get(&staged_id)
            .map(BrowserProfileLifecycleRecord::next),
        Some(State::Quarantined {
            reason: QuarantineReason::StartupProvisionInterrupted,
        })
    );
    assert_eq!(
        store
            .load_all()?
            .get(&leased_id)
            .map(BrowserProfileLifecycleRecord::next),
        Some(State::Quarantined {
            reason: QuarantineReason::StartupLeaseInterrupted,
        })
    );
    let loaded = store.load_all()?;
    let leased_record = loaded
        .get(&leased_id)
        .ok_or("quarantined lease record is missing")?;
    assert_eq!(leased_record.latest_generation(), Some(generation(6)?));
    assert_eq!(
        store
            .load_all()?
            .get(&available_id)
            .map(BrowserProfileLifecycleRecord::next),
        Some(State::Available)
    );
    assert_eq!(
        store.classify_abandoned_on_startup(observed_at()?)?.len(),
        0
    );
    assert!(directory.path().join("profile-staged.json").is_file());
    Ok(())
}
