#![allow(
    clippy::panic_in_result_fn,
    reason = "test assertions provide clearer warm-plan invariant diagnostics"
)]

use crate::internal::web_capture as internal_web_capture;
use std::error::Error;

use crate::internal::web_capture::{
    BrowserNavigationReadinessCheckpoint, BrowserProfileId, BrowserProfileOwnerId, NewProfileSpec,
    ProfileWarmBounds, ProfileWarmPlan, ProfileWarmPlanError, ProfileWarmPlanId,
    ProfileWarmProcessCleanup, ProfileWarmProfileDisposition, ProfileWarmStep,
    ProfileWarmStepReceipt, ProfileWarmTerminalReason, ProfileWarmTerminalReceipt,
    RequestedWebTarget,
};

fn bounds() -> Result<ProfileWarmBounds, ProfileWarmPlanError> {
    ProfileWarmBounds::new(4, 30_000, 120_000)
}

fn targets() -> Result<Vec<RequestedWebTarget>, Box<dyn Error>> {
    Ok(vec![
        RequestedWebTarget::parse("https://warm-one.example/path?token=secret-one")?,
        RequestedWebTarget::parse("https://warm-two.example/path?auth=secret-two")?,
    ])
}

fn plan(id: ProfileWarmPlanId) -> Result<ProfileWarmPlan, Box<dyn Error>> {
    Ok(ProfileWarmPlan::with_id(
        id,
        targets()?,
        bounds()?,
        BrowserNavigationReadinessCheckpoint::Load,
    )?)
}

#[test]
fn rejects_invalid_plans_and_bounds() -> Result<(), Box<dyn Error>> {
    let valid_bounds = bounds()?;
    let id = ProfileWarmPlanId::random();

    assert_eq!(
        ProfileWarmPlan::with_id(
            id,
            Vec::new(),
            valid_bounds,
            BrowserNavigationReadinessCheckpoint::Load,
        ),
        Err(ProfileWarmPlanError::EmptyPlan)
    );

    let duplicate = RequestedWebTarget::parse("https://same.example/path")?;
    assert_eq!(
        ProfileWarmPlan::with_id(
            id,
            vec![duplicate.clone(), duplicate],
            valid_bounds,
            BrowserNavigationReadinessCheckpoint::Load,
        ),
        Err(ProfileWarmPlanError::DuplicateTarget)
    );

    assert_eq!(
        ProfileWarmBounds::new(0, 1_000, 2_000),
        Err(ProfileWarmPlanError::ZeroTargetLimit)
    );
    assert_eq!(
        ProfileWarmBounds::new(
            internal_web_capture::MAX_PROFILE_WARM_TARGETS + 1,
            1_000,
            2_000
        ),
        Err(ProfileWarmPlanError::TargetLimitTooLarge)
    );
    let one_target_bounds = ProfileWarmBounds::new(1, 1_000, 2_000)?;
    assert_eq!(
        ProfileWarmPlan::with_id(
            id,
            targets()?,
            one_target_bounds,
            BrowserNavigationReadinessCheckpoint::Load,
        ),
        Err(ProfileWarmPlanError::TooManyTargets)
    );
    assert_eq!(
        ProfileWarmBounds::new(4, 2_000, 1_000),
        Err(ProfileWarmPlanError::OverallDeadlineShorterThanNavigation)
    );
    assert_eq!(
        ProfileWarmBounds::new(
            4,
            internal_web_capture::MAX_PROFILE_WARM_NAVIGATION_MILLISECONDS + 1,
            120_000,
        ),
        Err(ProfileWarmPlanError::NavigationDeadlineTooLarge)
    );
    assert_eq!(
        ProfileWarmBounds::new(
            4,
            1_000,
            internal_web_capture::MAX_PROFILE_WARM_OVERALL_MILLISECONDS + 1,
        ),
        Err(ProfileWarmPlanError::OverallDeadlineTooLarge)
    );
    assert_eq!(
        ProfileWarmPlan::with_id(
            id,
            targets()?,
            valid_bounds,
            BrowserNavigationReadinessCheckpoint::NetworkIdle,
        ),
        Err(ProfileWarmPlanError::UnsupportedReadiness)
    );
    Ok(())
}

#[test]
fn step_identities_are_stable_and_plan_debug_hides_target_urls() -> Result<(), Box<dyn Error>> {
    let id = ProfileWarmPlanId::random();
    let first = plan(id)?;
    let recreated = plan(id)?;

    assert_eq!(first.id(), recreated.id());
    assert_eq!(
        first
            .steps()
            .iter()
            .map(ProfileWarmStep::id)
            .collect::<Vec<_>>(),
        recreated
            .steps()
            .iter()
            .map(ProfileWarmStep::id)
            .collect::<Vec<_>>()
    );
    assert_eq!(first.steps()[0].id().number().get(), 1);
    assert_eq!(first.steps()[1].id().number().get(), 2);

    let debug = format!("{first:?}");
    assert!(!debug.contains("secret-one"));
    assert!(!debug.contains("secret-two"));
    Ok(())
}

#[test]
fn terminal_receipt_is_ordered_and_contains_no_target_urls() -> Result<(), Box<dyn Error>> {
    let plan = plan(ProfileWarmPlanId::random())?;
    let spec = NewProfileSpec::new(
        BrowserProfileId::new("warm-profile")?,
        BrowserProfileOwnerId::random(),
    );
    let steps = plan
        .steps()
        .iter()
        .map(|step| ProfileWarmStepReceipt::not_attempted(step.id()))
        .collect();
    let receipt = ProfileWarmTerminalReceipt::new(
        &spec,
        &plan,
        steps,
        ProfileWarmTerminalReason::StagingFailed,
        ProfileWarmProcessCleanup::ConfirmedClosed,
        ProfileWarmProfileDisposition::Removed,
    )?;
    let encoded = serde_json::to_string(&receipt)?;
    let decoded: ProfileWarmTerminalReceipt = serde_json::from_str(&encoded)?;

    assert!(!encoded.contains("warm-one.example"));
    assert!(!encoded.contains("secret-one"));
    assert!(!encoded.contains("warm-two.example"));
    assert!(!encoded.contains("secret-two"));
    assert_eq!(receipt.steps().len(), plan.steps().len());
    assert_eq!(receipt.bounds(), plan.bounds());
    assert_eq!(receipt.readiness(), plan.readiness());
    assert_eq!(receipt.owner_id(), spec.owner_id());
    assert_eq!(decoded, receipt);

    let mut wrong_step_order: serde_json::Value = serde_json::from_str(&encoded)?;
    wrong_step_order["steps"][0]["step"]["number"] = serde_json::Value::from(2);
    assert!(serde_json::from_value::<ProfileWarmTerminalReceipt>(wrong_step_order).is_err());

    let mut published_before_success: serde_json::Value = serde_json::from_str(&encoded)?;
    published_before_success["profile_disposition"] =
        serde_json::Value::String("published_available".to_owned());
    assert!(
        serde_json::from_value::<ProfileWarmTerminalReceipt>(published_before_success).is_err()
    );

    let mut contradictory_bounds: serde_json::Value = serde_json::from_str(&encoded)?;
    contradictory_bounds["bounds"]["overall_milliseconds"] = serde_json::Value::from(1_000);
    assert!(serde_json::from_value::<ProfileWarmTerminalReceipt>(contradictory_bounds).is_err());
    Ok(())
}

#[test]
fn incomplete_or_unclean_warm_up_cannot_be_published() -> Result<(), Box<dyn Error>> {
    let plan = plan(ProfileWarmPlanId::random())?;
    let spec = NewProfileSpec::new(
        BrowserProfileId::new("warm-profile")?,
        BrowserProfileOwnerId::random(),
    );
    let steps = plan
        .steps()
        .iter()
        .map(|step| ProfileWarmStepReceipt::not_attempted(step.id()))
        .collect();

    assert!(
        ProfileWarmTerminalReceipt::new(
            &spec,
            &plan,
            steps,
            ProfileWarmTerminalReason::StagingFailed,
            ProfileWarmProcessCleanup::DeadlineExceeded,
            ProfileWarmProfileDisposition::PublishedAvailable,
        )
        .is_err()
    );
    Ok(())
}
