use crate::{BrowserExecutionReceipt, CaptureEnvironment, WebAcquisitionRecord};

use super::WebCaptureError;

pub(super) fn validate_browser_execution(
    acquisition: &WebAcquisitionRecord,
    environment: &CaptureEnvironment,
    receipt: &BrowserExecutionReceipt,
) -> Result<(), WebCaptureError> {
    if receipt.capture_id() != acquisition.receipt().id() {
        return Err(WebCaptureError::ForeignBrowserExecution);
    }
    if !browser_acquisition(acquisition) {
        return Err(WebCaptureError::BrowserExecutionStrategyMismatch);
    }
    if !matches!(environment, CaptureEnvironment::Browser(_)) {
        return Err(WebCaptureError::BrowserExecutionEnvironmentMismatch);
    }
    Ok(())
}

pub(super) const fn validate_browser_challenge(
    acquisition: &WebAcquisitionRecord,
    environment: &CaptureEnvironment,
) -> Result<(), WebCaptureError> {
    if !browser_acquisition(acquisition) {
        return Err(WebCaptureError::BrowserChallengeStrategyMismatch);
    }
    if !matches!(environment, CaptureEnvironment::Browser(_)) {
        return Err(WebCaptureError::BrowserChallengeEnvironmentMismatch);
    }
    Ok(())
}

const fn browser_acquisition(acquisition: &WebAcquisitionRecord) -> bool {
    matches!(
        acquisition.request().strategy(),
        crate::WebAcquisitionStrategy::PageContextFetch(_)
            | crate::WebAcquisitionStrategy::DocumentNavigation(_)
    )
}
