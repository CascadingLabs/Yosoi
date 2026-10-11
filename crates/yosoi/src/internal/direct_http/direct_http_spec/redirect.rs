//! Validated redirect bounds and policy for Direct HTTP capture.

use std::num::NonZeroU32;

use super::DirectHttpCaptureSpecError;

/// Positive maximum number of redirect transitions admitted by an attempt.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct RedirectHopLimit(NonZeroU32);

impl RedirectHopLimit {
    /// Returns the exact positive hop bound.
    pub const fn get(self) -> u32 {
        self.0.get()
    }
}

impl TryFrom<u32> for RedirectHopLimit {
    type Error = DirectHttpCaptureSpecError;

    fn try_from(value: u32) -> Result<Self, Self::Error> {
        NonZeroU32::new(value)
            .map(Self)
            .ok_or(DirectHttpCaptureSpecError::ZeroRedirectHopLimit)
    }
}

/// Redirect behavior for one Direct HTTP attempt.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DirectHttpRedirectPolicy {
    /// Return the first response without following its `Location` value.
    Disabled,
    /// Follow redirects up to the positive hop bound.
    Follow { max_hops: RedirectHopLimit },
}

impl DirectHttpRedirectPolicy {
    /// Constructs follow behavior from an already validated positive bound.
    pub const fn follow(max_hops: RedirectHopLimit) -> Self {
        Self::Follow { max_hops }
    }

    /// Returns the follow bound, or `None` when redirects are disabled.
    pub const fn max_hops(self) -> Option<RedirectHopLimit> {
        match self {
            Self::Disabled => None,
            Self::Follow { max_hops } => Some(max_hops),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redirect_hop_limit_rejects_zero() {
        assert_eq!(
            RedirectHopLimit::try_from(0),
            Err(DirectHttpCaptureSpecError::ZeroRedirectHopLimit)
        );
    }

    #[test]
    fn redirect_policy_preserves_positive_bound_and_disabled_state() {
        let maximum = RedirectHopLimit::try_from(u32::MAX).unwrap();
        let policy = DirectHttpRedirectPolicy::follow(maximum);
        assert_eq!(policy.max_hops(), Some(maximum));
        assert_eq!(policy.max_hops().map(RedirectHopLimit::get), Some(u32::MAX));
        assert_eq!(DirectHttpRedirectPolicy::Disabled.max_hops(), None);
    }
}
