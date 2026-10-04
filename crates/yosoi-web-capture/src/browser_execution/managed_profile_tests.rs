use chrono::{DateTime, Duration as WallDuration, Utc};
use std::{
    num::NonZeroU64,
    sync::Arc,
    time::{Duration, Instant},
};

use super::*;
use crate::{BrowserProfileLeaseGeneration, BrowserProfileLeaseId, BrowserProfileOwnerId};

fn profile_id() -> BrowserProfileId {
    BrowserProfileId::new(format!("test-{}", BrowserProfileLeaseId::random()))
        .expect("test profile id is valid")
}

#[test]
fn lease_generations_increase_per_profile_and_expiry_uses_monotonic_time() {
    let profile = profile_id();
    let generations = Arc::new(BrowserProfileLeaseGenerationRegistry::default());
    let generation = generations
        .next_generation(&profile)
        .expect("first generation");

    let monotonic_start = Instant::now();
    let wall_start =
        DateTime::<Utc>::from_timestamp(1_800_000_000, 0).expect("fixed test timestamp is valid");
    let first_fence = BrowserProfileLeaseFence::start(
        profile.clone(),
        BrowserProfileLeaseId::random(),
        BrowserProfileOwnerId::random(),
        generation,
        Arc::clone(&generations),
        Duration::from_secs(30),
        monotonic_start,
        wall_start,
    )
    .expect("valid test lease window");
    assert_eq!(first_fence.authorize(generation, monotonic_start), Ok(()));

    let next_generation = generations
        .next_generation(&profile)
        .expect("next generation");
    assert_eq!(next_generation.get(), generation.get() + 1);
    assert_eq!(
        first_fence.authorize(generation, monotonic_start),
        Err(BrowserProfileLeaseError::StaleGeneration)
    );

    let fence = BrowserProfileLeaseFence::start(
        profile,
        BrowserProfileLeaseId::random(),
        BrowserProfileOwnerId::random(),
        next_generation,
        Arc::clone(&generations),
        Duration::from_secs(30),
        monotonic_start,
        wall_start,
    )
    .expect("valid newer lease window");
    assert_eq!(fence.authorize(next_generation, monotonic_start), Ok(()));
    assert!(fence.expired_at(monotonic_start + Duration::from_secs(30)));
    assert_eq!(
        fence.authorize(next_generation, monotonic_start + Duration::from_secs(30)),
        Err(BrowserProfileLeaseError::Expired)
    );
    assert_eq!(fence.receipt().acquired_at(), &wall_start);
    assert_eq!(
        fence.receipt().expires_at(),
        &(wall_start + WallDuration::seconds(30))
    );
}

#[test]
fn lease_receipt_round_trip_is_validated_and_omits_runtime_paths() {
    let acquired_at =
        DateTime::<Utc>::from_timestamp(1_800_000_000, 0).expect("fixed test timestamp is valid");
    let receipt = BrowserProfileLeaseReceipt::new(
        profile_id(),
        BrowserProfileLeaseId::random(),
        BrowserProfileOwnerId::random(),
        BrowserProfileLeaseScope::ExclusiveManagedBrowser,
        BrowserProfileLeaseGeneration::new(NonZeroU64::new(1).unwrap_or(NonZeroU64::MIN)),
        acquired_at,
        acquired_at + WallDuration::seconds(30),
    )
    .expect("valid receipt");
    let encoded = serde_json::to_string(&receipt).expect("receipt serialization");
    let decoded: BrowserProfileLeaseReceipt =
        serde_json::from_str(&encoded).expect("receipt round trip");
    assert_eq!(decoded, receipt);
    assert!(!encoded.contains("path"));
    assert!(!encoded.contains("cookie"));
}

#[test]
fn terminal_receipt_marks_ownership_uncertainty_as_quarantine_required() {
    let acquired_at =
        DateTime::<Utc>::from_timestamp(1_800_000_000, 0).expect("fixed test timestamp is valid");
    let lease = BrowserProfileLeaseReceipt::new(
        profile_id(),
        BrowserProfileLeaseId::random(),
        BrowserProfileOwnerId::random(),
        BrowserProfileLeaseScope::ExclusiveManagedBrowser,
        BrowserProfileLeaseGeneration::new(NonZeroU64::new(1).unwrap_or(NonZeroU64::MIN)),
        acquired_at,
        acquired_at + WallDuration::seconds(30),
    )
    .expect("valid receipt");
    let terminal = BrowserProfileLeaseTerminalReceipt::new(
        lease,
        BrowserProfileLeaseTerminalOutcome::OwnershipUncertain,
        acquired_at + WallDuration::seconds(1),
    )
    .expect("valid terminal receipt");
    assert!(terminal.outcome().quarantine_required());
}

#[test]
fn terminal_receipt_rejects_times_that_contradict_its_wall_clock_window() {
    let acquired_at =
        DateTime::<Utc>::from_timestamp(1_800_000_000, 0).expect("fixed test timestamp is valid");
    let lease = BrowserProfileLeaseReceipt::new(
        profile_id(),
        BrowserProfileLeaseId::random(),
        BrowserProfileOwnerId::random(),
        BrowserProfileLeaseScope::ExclusiveManagedBrowser,
        BrowserProfileLeaseGeneration::new(NonZeroU64::new(1).unwrap_or(NonZeroU64::MIN)),
        acquired_at,
        acquired_at + WallDuration::seconds(30),
    )
    .expect("valid receipt");

    assert_eq!(
        BrowserProfileLeaseTerminalReceipt::new(
            lease.clone(),
            BrowserProfileLeaseTerminalOutcome::Released,
            acquired_at - WallDuration::seconds(1),
        ),
        Err(BrowserProfileLeaseError::InvalidTerminalTime)
    );
    assert_eq!(
        BrowserProfileLeaseTerminalReceipt::new(
            lease,
            BrowserProfileLeaseTerminalOutcome::ExpiredAndReleased,
            acquired_at + WallDuration::seconds(1),
        ),
        Err(BrowserProfileLeaseError::ExpiredBeforeDeadline)
    );
}
