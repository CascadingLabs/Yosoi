use crate::internal::browser::{AccessibilitySnapshotOptions, VoidCrawlError, error::Result};

pub(super) const fn event_overflow(operation: &'static str) -> VoidCrawlError {
    VoidCrawlError::InvalidInput {
        operation,
        reason: "provider event listener overflowed",
    }
}

pub(super) fn positive_u32(value: f64) -> u32 {
    if !value.is_finite() || value <= 0.0 {
        return 0;
    }
    format!("{value:.0}").parse().unwrap_or(0)
}

pub(super) fn validate_accessibility_options(options: AccessibilitySnapshotOptions) -> Result<()> {
    if options.max_nodes == 0 || options.max_bytes < 2 {
        return Err(VoidCrawlError::InvalidInput {
            operation: "accessibility_snapshot",
            reason: "max_nodes must be positive and max_bytes must fit an empty JSON array",
        });
    }
    if options.depth.is_some_and(|depth| depth < 0) {
        return Err(VoidCrawlError::InvalidInput {
            operation: "accessibility_snapshot",
            reason: "depth must be non-negative",
        });
    }
    Ok(())
}
