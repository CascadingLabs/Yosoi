use std::{collections::HashMap, num::NonZeroU64, sync::Mutex};

#[cfg(any(feature = "browser", test))]
use std::{
    sync::Arc,
    time::{Duration, Instant},
};

#[cfg(any(feature = "browser", test))]
use chrono::{DateTime, Duration as WallDuration, Utc};

use super::super::BrowserProfileLeaseGeneration;
#[cfg(any(feature = "browser", test))]
use super::super::{BrowserProfileLeaseId, BrowserProfileOwnerId};
use super::{BrowserProfileId, BrowserProfileLeaseError};
#[cfg(any(feature = "browser", test))]
use super::{BrowserProfileLeaseReceipt, BrowserProfileLeaseScope};

/// Yosoi-owned monotonic generation allocator shared across manager recreation.
///
/// Keep one allocator for the lifetime of the profile-owning application
/// service and pass it to each managed-profile tenancy. It contains no provider
/// handles, registry paths, or profile state.
#[derive(Debug, Default)]
pub struct BrowserProfileLeaseGenerationRegistry {
    generations: Mutex<HashMap<BrowserProfileId, u64>>,
}

impl BrowserProfileLeaseGenerationRegistry {
    pub fn next_generation(
        &self,
        profile_id: &BrowserProfileId,
    ) -> Result<BrowserProfileLeaseGeneration, BrowserProfileLeaseError> {
        self.next_generation_after(profile_id, None)
    }

    /// Allocates a generation above both this process's watermark and the
    /// durable lifecycle watermark observed by the caller.
    pub fn next_generation_after(
        &self,
        profile_id: &BrowserProfileId,
        persisted_generation: Option<BrowserProfileLeaseGeneration>,
    ) -> Result<BrowserProfileLeaseGeneration, BrowserProfileLeaseError> {
        let generation = {
            let mut generations = self
                .generations
                .lock()
                .map_err(|_| BrowserProfileLeaseError::GenerationAllocatorUnavailable)?;
            let in_process_generation = generations.get(profile_id).copied().unwrap_or(0);
            let persisted_generation =
                persisted_generation.map_or(0, BrowserProfileLeaseGeneration::get);
            let next = in_process_generation
                .max(persisted_generation)
                .checked_add(1)
                .ok_or(BrowserProfileLeaseError::GenerationExhausted)?;
            let generation =
                NonZeroU64::new(next).ok_or(BrowserProfileLeaseError::GenerationExhausted)?;
            generations.insert(profile_id.clone(), next);
            generation
        };
        Ok(BrowserProfileLeaseGeneration::new(generation))
    }

    pub(in crate::internal::web_capture) fn is_current(
        &self,
        profile_id: &BrowserProfileId,
        generation: BrowserProfileLeaseGeneration,
    ) -> Result<bool, BrowserProfileLeaseError> {
        let generations = self
            .generations
            .lock()
            .map_err(|_| BrowserProfileLeaseError::GenerationAllocatorUnavailable)?;
        Ok(generations.get(profile_id).copied() == Some(generation.get()))
    }
}

/// Manager-owned profile fence. The profile generation is distinct from
/// browser process generations because a tenancy can outlive process recycling.
#[derive(Clone, Debug)]
#[cfg(any(feature = "browser", test))]
pub struct BrowserProfileLeaseFence {
    receipt: BrowserProfileLeaseReceipt,
    generations: Arc<BrowserProfileLeaseGenerationRegistry>,
    deadline: Instant,
}

#[cfg(any(feature = "browser", test))]
impl BrowserProfileLeaseFence {
    #[allow(clippy::too_many_arguments)]
    pub(in crate::internal::web_capture) fn start(
        profile_id: BrowserProfileId,
        lease_id: BrowserProfileLeaseId,
        owner_id: BrowserProfileOwnerId,
        generation: BrowserProfileLeaseGeneration,
        generations: Arc<BrowserProfileLeaseGenerationRegistry>,
        duration: Duration,
        monotonic_now: Instant,
        wall_now: DateTime<Utc>,
    ) -> Result<Self, BrowserProfileLeaseError> {
        if duration.is_zero() {
            return Err(BrowserProfileLeaseError::ZeroDuration);
        }
        let deadline = monotonic_now
            .checked_add(duration)
            .ok_or(BrowserProfileLeaseError::DeadlineOverflow)?;
        let wall_duration = WallDuration::from_std(duration)
            .map_err(|_| BrowserProfileLeaseError::DeadlineOverflow)?;
        let expires_at = wall_now
            .checked_add_signed(wall_duration)
            .ok_or(BrowserProfileLeaseError::DeadlineOverflow)?;
        let receipt = BrowserProfileLeaseReceipt::new(
            profile_id,
            lease_id,
            owner_id,
            BrowserProfileLeaseScope::ExclusiveManagedBrowser,
            generation,
            wall_now,
            expires_at,
        )?;
        if !generations.is_current(receipt.profile_id(), generation)? {
            return Err(BrowserProfileLeaseError::StaleGeneration);
        }
        Ok(Self {
            receipt,
            generations,
            deadline,
        })
    }

    pub(in crate::internal::web_capture) const fn receipt(&self) -> &BrowserProfileLeaseReceipt {
        &self.receipt
    }

    pub(in crate::internal::web_capture) const fn generation(
        &self,
    ) -> BrowserProfileLeaseGeneration {
        self.receipt.generation()
    }

    pub(in crate::internal::web_capture) const fn deadline(&self) -> Instant {
        self.deadline
    }

    pub(in crate::internal::web_capture) fn authorize(
        &self,
        generation: BrowserProfileLeaseGeneration,
        now: Instant,
    ) -> Result<(), BrowserProfileLeaseError> {
        if generation != self.generation() {
            return Err(BrowserProfileLeaseError::StaleGeneration);
        }
        if !self
            .generations
            .is_current(self.receipt.profile_id(), generation)?
        {
            return Err(BrowserProfileLeaseError::StaleGeneration);
        }
        if now >= self.deadline {
            return Err(BrowserProfileLeaseError::Expired);
        }
        Ok(())
    }

    pub(in crate::internal::web_capture) fn expired_at(&self, now: Instant) -> bool {
        now >= self.deadline
    }
}
