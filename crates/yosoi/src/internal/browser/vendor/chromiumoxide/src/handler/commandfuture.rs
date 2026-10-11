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

        method: MethodId,

        _marker: PhantomData<T>
    }
}

impl<T: Command> CommandFuture<T> {
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
        } else if this.delay.poll(cx).is_ready() {
            Poll::Ready(Err(
                crate::internal::browser::vendor::chromiumoxide::error::CdpError::Timeout,
            ))
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

    use super::*;

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
