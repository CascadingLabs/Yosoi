use std::fmt;

use tokio::sync::{mpsc, oneshot};
use tokio_util::sync::CancellationToken;

use crate as yosoi;

use super::BrowserNavigationSchedulerError;

pub struct BrowserNavigationHandle {
    id: yosoi::BrowserNavigationRequestId,
    request: yosoi::BrowserNavigationRequest,
    progress: mpsc::Receiver<yosoi::BrowserNavigationProgressReceipt>,
    readiness: Option<oneshot::Receiver<ReadinessSignal>>,
    terminal: Option<oneshot::Receiver<yosoi::BrowserNavigationTerminalReceipt>>,
    cancellation: CancellationToken,
    finished: bool,
}

pub(super) enum ReadinessSignal {
    Reached(yosoi::BrowserNavigationProgressReceipt),
    Ended(yosoi::BrowserNavigationOutcome),
}

impl BrowserNavigationHandle {
    pub(super) const fn new(
        request: yosoi::BrowserNavigationRequest,
        progress: mpsc::Receiver<yosoi::BrowserNavigationProgressReceipt>,
        readiness: oneshot::Receiver<ReadinessSignal>,
        terminal: oneshot::Receiver<yosoi::BrowserNavigationTerminalReceipt>,
        cancellation: CancellationToken,
    ) -> Self {
        Self {
            id: request.request(),
            request,
            progress,
            readiness: Some(readiness),
            terminal: Some(terminal),
            cancellation,
            finished: false,
        }
    }

    pub const fn id(&self) -> yosoi::BrowserNavigationRequestId {
        self.id
    }

    pub async fn next_milestone(
        &mut self,
    ) -> Result<Option<yosoi::BrowserNavigationProgressReceipt>, BrowserNavigationSchedulerError>
    {
        Ok(self.progress.recv().await)
    }

    pub async fn wait_until_ready(
        &mut self,
    ) -> Result<yosoi::BrowserNavigationProgressReceipt, BrowserNavigationSchedulerError> {
        let signal = {
            let readiness = self
                .readiness
                .as_mut()
                .ok_or(BrowserNavigationSchedulerError::InternalInvariant)?;
            readiness
                .await
                .map_err(|_| BrowserNavigationSchedulerError::InternalInvariant)?
        };
        self.readiness = None;
        match signal {
            ReadinessSignal::Reached(receipt) => Ok(receipt),
            ReadinessSignal::Ended(outcome) => {
                Err(BrowserNavigationSchedulerError::EndedBeforeReadiness { outcome })
            }
        }
    }

    pub async fn wait(
        mut self,
    ) -> Result<yosoi::BrowserNavigationTerminalReceipt, BrowserNavigationSchedulerError> {
        let terminal = self
            .terminal
            .take()
            .ok_or(BrowserNavigationSchedulerError::InternalInvariant)?;
        let receipt = terminal
            .await
            .unwrap_or_else(|_| runtime_failure_receipt(&self.request));
        self.finished = true;
        Ok(receipt)
    }

    pub async fn cancel(
        self,
    ) -> Result<yosoi::BrowserNavigationTerminalReceipt, BrowserNavigationSchedulerError> {
        self.cancellation.cancel();
        self.wait().await
    }
}

fn runtime_failure_receipt(
    request: &yosoi::BrowserNavigationRequest,
) -> yosoi::BrowserNavigationTerminalReceipt {
    yosoi::BrowserNavigationTerminalReceipt::new(
        request,
        yosoi::BrowserNavigationOutcome::Failed {
            reason: yosoi::BrowserNavigationFailure::InternalInvariant,
        },
        None,
        yosoi::BrowserNavigationProgressAccounting::empty(),
        yosoi::LossExtent::Unknown,
        yosoi::LossExtent::Unknown,
        yosoi::CaptureDuration::default(),
        yosoi::CaptureDuration::default(),
        false,
        false,
    )
}

impl fmt::Debug for BrowserNavigationHandle {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BrowserNavigationHandle")
            .field("id", &self.id)
            .finish_non_exhaustive()
    }
}

impl Drop for BrowserNavigationHandle {
    fn drop(&mut self) {
        if !self.finished {
            self.cancellation.cancel();
        }
    }
}
