use futures::channel::{
    mpsc,
    oneshot::{self, channel as oneshot_channel},
};
use pin_project_lite::pin_project;
use std::future::Future;
use std::marker::PhantomData;
use std::pin::Pin;
use std::task::{Context, Poll};

use crate::internal::browser::vendor::chromiumoxide::cmd::{CommandMessage, to_command_response};
use crate::internal::browser::vendor::chromiumoxide::error::Result;
use crate::internal::browser::vendor::chromiumoxide::handler::target::TargetMessage;
use crate::internal::browser::vendor::chromiumoxide_cdp::cdp::browser_protocol::target::SessionId;
use chromiumoxide_types::{Command, CommandResponse, MethodId, Response};

pin_project! {
    pub struct CommandFuture<T, M = Result<Response>> {
        #[pin]
        rx_command: oneshot::Receiver<M>,
        #[pin]
        target_sender: mpsc::Sender<TargetMessage>,
        // We need delay to be pinned because it's a future
        // and we need to be able to poll it
        // it is used to timeout the command if page was closed while waiting for response
        #[pin]
        delay: futures_timer::Delay,

        message: Option<TargetMessage>,
        response_deadline: Option<std::time::Instant>,

        method: MethodId,

        _marker: PhantomData<T>
    }
}

impl<T: Command> CommandFuture<T> {
    // Applied only at construction, before the command is polled/dispatched.
    pub(crate) fn before(mut self, deadline: std::time::Instant) -> Self {
        self.response_deadline = Some(deadline);
        if let Some(TargetMessage::Command(message) | TargetMessage::RawCommand(message)) =
            self.message.as_mut()
        {
            message.response_deadline = Some(deadline);
        }
        let remaining = deadline.saturating_duration_since(std::time::Instant::now());
        let remaining = if std::time::Instant::now().checked_add(remaining).is_some() {
            remaining
        } else {
            std::time::Duration::ZERO
        };
        self.delay.reset(remaining);
        self
    }

    pub fn new(
        cmd: T,
        target_sender: mpsc::Sender<TargetMessage>,
        session: Option<SessionId>,
    ) -> Result<Self> {
        let (tx, rx_command) = oneshot_channel::<Result<Response>>();
        let method = cmd.identifier();

        let message = Some(TargetMessage::Command(CommandMessage::with_session(
            cmd, tx, session,
        )?));

        let delay = futures_timer::Delay::new(std::time::Duration::from_millis(
            crate::internal::browser::vendor::chromiumoxide::handler::REQUEST_TIMEOUT,
        ));

        Ok(Self {
            target_sender,
            rx_command,
            message,
            response_deadline: None,
            delay,
            method,
            _marker: PhantomData,
        })
    }

    /// Creates a command future that bypasses Chromiumoxide navigation
    /// lifecycle tracking.
    pub fn new_raw(
        cmd: T,
        target_sender: mpsc::Sender<TargetMessage>,
        session: Option<SessionId>,
    ) -> Result<Self> {
        let (tx, rx_command) = oneshot_channel::<Result<Response>>();
        let method = cmd.identifier();
        let message = Some(TargetMessage::RawCommand(CommandMessage::with_session(
            cmd, tx, session,
        )?));
        let delay = futures_timer::Delay::new(std::time::Duration::from_millis(
            crate::internal::browser::vendor::chromiumoxide::handler::REQUEST_TIMEOUT,
        ));

        Ok(Self {
            target_sender,
            rx_command,
            message,
            response_deadline: None,
            delay,
            method,
            _marker: PhantomData,
        })
    }
}

impl<T> Future for CommandFuture<T>
where
    T: Command,
{
    type Output = Result<CommandResponse<T::Response>>;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let mut this = self.project();

        if this
            .response_deadline
            .as_ref()
            .is_some_and(|deadline| std::time::Instant::now() >= *deadline)
        {
            return Poll::Ready(Err(
                crate::internal::browser::vendor::chromiumoxide::error::CdpError::Timeout,
            ));
        }

        if this.delay.as_mut().poll(cx).is_ready() {
            return Poll::Ready(Err(
                crate::internal::browser::vendor::chromiumoxide::error::CdpError::Timeout,
            ));
        }

        if this.message.is_some() {
            match this.target_sender.poll_ready(cx) {
                Poll::Ready(Err(e)) => Poll::Ready(Err(e.into())),
                Poll::Ready(Ok(_)) => {
                    let Some(message) = this.message.take() else {
                        return Poll::Ready(Err(crate::internal::browser::vendor::chromiumoxide::error::CdpError::NoResponse));
                    };
                    this.target_sender.start_send(message)?;

                    cx.waker().wake_by_ref();
                    Poll::Pending
                }
                Poll::Pending => Poll::Pending,
            }
        } else {
            match this.rx_command.as_mut().poll(cx) {
                Poll::Ready(Ok(Ok(response))) => {
                    Poll::Ready(to_command_response::<T>(response, this.method.clone()))
                }
                Poll::Ready(Ok(Err(e))) => Poll::Ready(Err(e)),
                Poll::Ready(Err(e)) => Poll::Ready(Err(e.into())),
                Poll::Pending => Poll::Pending,
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::pin::Pin;
    use std::task::Poll;

    use futures::StreamExt;

    use crate::internal::browser::vendor::chromiumoxide_cdp::cdp::browser_protocol::page::NavigateParams;
    use crate::internal::browser::vendor::chromiumoxide_cdp::cdp::js_protocol::runtime::AwaitPromiseParams;

    use super::*;

    #[tokio::test]
    async fn expired_observation_deadline_prevents_dispatch() {
        let (sender, mut receiver) = mpsc::channel(1);
        let expired = std::time::Instant::now()
            .checked_sub(std::time::Duration::from_secs(1))
            .expect("fixture instant");
        let mut future =
            CommandFuture::new(AwaitPromiseParams::new("promise".to_owned()), sender, None)
                .expect("fixture command")
                .before(expired);
        let result = futures::future::poll_fn(|cx| Pin::new(&mut future).poll(cx)).await;
        assert!(matches!(
            result,
            Err(crate::internal::browser::vendor::chromiumoxide::error::CdpError::Timeout)
        ));
        assert!(
            receiver.try_recv().is_err(),
            "expired command must not reach the target"
        );
    }

    #[test]
    fn response_deadline_is_local_metadata_and_not_cdp_wire_data() {
        let (sender, _) = oneshot_channel::<Result<Response>>();
        let mut message =
            CommandMessage::new(AwaitPromiseParams::new("promise".to_owned()), sender)
                .expect("fixture command");
        message.response_deadline = Some(std::time::Instant::now());
        let wire = serde_json::to_value(message).expect("fixture serialization");
        assert_eq!(
            wire.get("method").and_then(|value| value.as_str()),
            Some("Runtime.awaitPromise")
        );
        assert!(wire.get("response_deadline").is_none());
    }

    #[tokio::test]
    async fn raw_navigation_command_bypasses_navigation_classification() {
        let (sender, mut receiver) = mpsc::channel(1);
        let mut future =
            CommandFuture::new_raw(NavigateParams::new("https://example.test/"), sender, None)
                .expect("navigate parameters are serializable");

        futures::future::poll_fn(|context| {
            let _ = Pin::new(&mut future).poll(context);
            Poll::Ready(())
        })
        .await;

        assert!(matches!(
            receiver.next().await,
            Some(TargetMessage::RawCommand(command)) if command.is_navigation()
        ));
    }
}
