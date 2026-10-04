use std::collections::HashMap;
use std::fmt;
use std::marker::PhantomData;
use std::num::{NonZeroU64, NonZeroUsize};
use std::pin::Pin;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::task::{Context, Poll};

use futures::Stream;
use futures::channel::mpsc::{Receiver, Sender, channel};

use chromiumoxide_cdp::cdp::{Event, EventKind, IntoEventKind};
use chromiumoxide_types::MethodId;

/// The behavior used when an event listener reaches its configured capacity.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EventOverflowPolicy {
    /// Retain earlier events and discard the newest event.
    DropNewest,
    /// Close the listener after discarding the event that exceeded capacity.
    Close,
}

/// Required bounds and overflow behavior for an event listener.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct EventListenerConfig {
    capacity: NonZeroUsize,
    overflow: EventOverflowPolicy,
}

impl EventListenerConfig {
    /// Creates a bounded event listener configuration.
    pub const fn new(capacity: NonZeroUsize, overflow: EventOverflowPolicy) -> Self {
        Self { capacity, overflow }
    }

    /// Returns the maximum number of retained events.
    pub const fn capacity(&self) -> NonZeroUsize {
        self.capacity
    }

    /// Returns the configured overflow behavior.
    pub const fn overflow(&self) -> EventOverflowPolicy {
        self.overflow
    }
}

/// A delivered event or an exact count of events lost before the next event.
#[derive(Debug)]
pub enum EventDelivery<T> {
    /// A retained event, in source order.
    Event(Arc<T>),
    /// Events were dropped before the next retained event or stream closure.
    Lagged { dropped: NonZeroU64 },
}

#[derive(Debug)]
struct ListenerAccounting {
    last_dispatched: AtomicU64,
}

struct EventEnvelope {
    sequence: NonZeroU64,
    event: Arc<dyn Event>,
}

/// All the currently active listeners.
#[derive(Debug, Default)]
pub struct EventListeners {
    /// Tracks the listeners for each event identified by the key.
    listeners: HashMap<MethodId, Vec<EventListener>>,
}

impl EventListeners {
    /// Register a subscription for a method.
    pub fn add_listener(&mut self, req: EventListenerRequest) {
        let EventListenerRequest {
            listener,
            method,
            kind,
            overflow,
            accounting,
        } = req;
        self.listeners
            .entry(method)
            .or_default()
            .push(EventListener {
                listener,
                kind,
                overflow,
                accounting,
                last_dispatched: 0,
            });
    }

    /// Remove dropped receivers even when their event method is quiet.
    pub fn prune_closed(&mut self) {
        self.listeners.retain(|_, subscriptions| {
            subscriptions.retain(|listener| !listener.is_closed());
            !subscriptions.is_empty()
        });
    }

    /// Delivers an event without awaiting or buffering outside the listener's
    /// configured channel. Closed listeners are removed on the next dispatch.
    pub fn start_send<T: Event>(&mut self, event: T) {
        if let Some(subscriptions) = self.listeners.get_mut(&T::method_id()) {
            let event: Arc<dyn Event> = Arc::new(event);
            subscriptions.retain_mut(|listener| listener.start_send(Arc::clone(&event)));
        }
    }

    /// Tries to deliver a custom event when a listener is registered and the
    /// JSON value can be converted to the registered event type.
    pub fn try_send_custom(
        &mut self,
        method: &str,
        val: serde_json::Value,
    ) -> serde_json::Result<()> {
        if let Some(subscriptions) = self.listeners.get_mut(method) {
            let event = subscriptions
                .iter()
                .find_map(|listener| {
                    if let EventKind::Custom(convert) = &listener.kind {
                        Some(convert(val.clone()))
                    } else {
                        None
                    }
                })
                .transpose()?;

            if let Some(event) = event {
                subscriptions.retain_mut(|listener| {
                    !listener.kind.is_custom() || listener.start_send(Arc::clone(&event))
                });
            }
        }
        Ok(())
    }
}

/// A request to register a bounded event listener.
pub struct EventListenerRequest {
    listener: Sender<EventEnvelope>,
    method: MethodId,
    kind: EventKind,
    overflow: EventOverflowPolicy,
    accounting: Arc<ListenerAccounting>,
}

impl EventListenerRequest {
    /// Creates the handler registration request and its matching event stream.
    pub fn new<T: IntoEventKind>(config: EventListenerConfig) -> (Self, EventStream<T>) {
        // futures::mpsc reserves one sender slot beyond the channel argument.
        // This listener has one sender, so subtracting one preserves the public
        // capacity exactly without introducing another queue.
        let channel_capacity = config.capacity.get().saturating_sub(1);
        let (listener, events) = channel(channel_capacity);
        let accounting = Arc::new(ListenerAccounting {
            last_dispatched: AtomicU64::new(0),
        });
        let stream = EventStream {
            events,
            accounting: Arc::clone(&accounting),
            pending: None,
            last_delivered: 0,
            _marker: PhantomData,
        };

        (
            Self {
                listener,
                method: T::method_id(),
                kind: T::event_kind(),
                overflow: config.overflow,
                accounting,
            },
            stream,
        )
    }
}

impl fmt::Debug for EventListenerRequest {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("EventListenerRequest")
            .field("method", &self.method)
            .field("kind", &self.kind)
            .field("overflow", &self.overflow)
            .finish()
    }
}

/// Represents a single event listener.
pub struct EventListener {
    listener: Sender<EventEnvelope>,
    kind: EventKind,
    overflow: EventOverflowPolicy,
    accounting: Arc<ListenerAccounting>,
    last_dispatched: u64,
}

impl EventListener {
    fn is_closed(&self) -> bool {
        self.listener.is_closed()
    }

    /// Delivers an event immediately. `false` removes a closed listener.
    pub fn start_send(&mut self, event: Arc<dyn Event>) -> bool {
        if self.listener.is_closed() {
            return false;
        }

        let Some(next_sequence) = self.last_dispatched.checked_add(1) else {
            self.listener.close_channel();
            return false;
        };
        let Some(sequence) = NonZeroU64::new(next_sequence) else {
            self.listener.close_channel();
            return false;
        };

        self.last_dispatched = next_sequence;
        self.accounting
            .last_dispatched
            .store(next_sequence, Ordering::Release);

        match self.listener.try_send(EventEnvelope { sequence, event }) {
            Ok(()) => true,
            Err(error) if error.is_full() => match self.overflow {
                EventOverflowPolicy::DropNewest => true,
                EventOverflowPolicy::Close => {
                    self.listener.close_channel();
                    false
                }
            },
            Err(_) => false,
        }
    }
}

impl fmt::Debug for EventListener {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("EventListener")
            .field("kind", &self.kind)
            .field("overflow", &self.overflow)
            .finish()
    }
}

/// The receiver part of a bounded event subscription.
pub struct EventStream<T: IntoEventKind> {
    events: Receiver<EventEnvelope>,
    accounting: Arc<ListenerAccounting>,
    pending: Option<EventEnvelope>,
    last_delivered: u64,
    _marker: PhantomData<T>,
}

impl<T: IntoEventKind> fmt::Debug for EventStream<T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("EventStream").finish()
    }
}

impl<T: IntoEventKind + Unpin> Stream for EventStream<T> {
    type Item = EventDelivery<T>;

    fn poll_next(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        let stream = self.get_mut();

        loop {
            if let Some(envelope) = stream.pending.take() {
                stream.last_delivered = envelope.sequence.get();
                if let Ok(event) = envelope.event.into_any_arc().downcast() {
                    return Poll::Ready(Some(EventDelivery::Event(event)));
                }
                continue;
            }

            match Stream::poll_next(Pin::new(&mut stream.events), cx) {
                Poll::Ready(Some(envelope)) => {
                    let missing = envelope
                        .sequence
                        .get()
                        .checked_sub(stream.last_delivered)
                        .and_then(|difference| difference.checked_sub(1))
                        .and_then(NonZeroU64::new);
                    stream.pending = Some(envelope);
                    if let Some(dropped) = missing {
                        return Poll::Ready(Some(EventDelivery::Lagged { dropped }));
                    }
                }
                Poll::Ready(None) => {
                    let last_dispatched = stream.accounting.last_dispatched.load(Ordering::Acquire);
                    let missing = last_dispatched
                        .checked_sub(stream.last_delivered)
                        .and_then(NonZeroU64::new);
                    if let Some(dropped) = missing {
                        stream.last_delivered = last_dispatched;
                        return Poll::Ready(Some(EventDelivery::Lagged { dropped }));
                    }
                    return Poll::Ready(None);
                }
                Poll::Pending => {
                    let last_dispatched = stream.accounting.last_dispatched.load(Ordering::Acquire);
                    let missing = last_dispatched
                        .checked_sub(stream.last_delivered)
                        .and_then(NonZeroU64::new);
                    if let Some(dropped) = missing {
                        stream.last_delivered = last_dispatched;
                        return Poll::Ready(Some(EventDelivery::Lagged { dropped }));
                    }
                    return Poll::Pending;
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroUsize;

    use futures::StreamExt;

    use chromiumoxide_cdp::cdp::browser_protocol::animation::EventAnimationCanceled;
    use chromiumoxide_types::MethodType;

    use super::*;

    fn config(capacity: NonZeroUsize) -> EventListenerConfig {
        EventListenerConfig::new(capacity, EventOverflowPolicy::DropNewest)
    }

    fn event(id: &str) -> EventAnimationCanceled {
        EventAnimationCanceled { id: id.to_string() }
    }

    #[tokio::test]
    async fn listener_retains_exact_configured_capacity() {
        let mut listeners = EventListeners::default();
        let (request, mut stream) = EventListenerRequest::new::<EventAnimationCanceled>(config(
            NonZeroUsize::new(2).expect("test capacity is non-zero"),
        ));
        listeners.add_listener(request);

        listeners.start_send(event("first"));
        listeners.start_send(event("second"));

        let Some(EventDelivery::Event(first)) = stream.next().await else {
            panic!("first retained event was not delivered");
        };
        let Some(EventDelivery::Event(second)) = stream.next().await else {
            panic!("second retained event was not delivered");
        };
        assert_eq!(first.id, "first");
        assert_eq!(second.id, "second");
    }

    #[tokio::test]
    async fn listener_reports_dropped_newest_events() {
        let mut listeners = EventListeners::default();
        let (request, mut stream) = EventListenerRequest::new::<EventAnimationCanceled>(config(
            NonZeroUsize::new(2).expect("test capacity is non-zero"),
        ));
        listeners.add_listener(request);

        listeners.start_send(event("first"));
        listeners.start_send(event("second"));
        listeners.start_send(event("dropped"));

        let Some(EventDelivery::Event(_)) = stream.next().await else {
            panic!("first retained event was not delivered");
        };
        let Some(EventDelivery::Event(_)) = stream.next().await else {
            panic!("second retained event was not delivered");
        };

        listeners.start_send(event("after-loss"));
        let Some(EventDelivery::Lagged { dropped }) = stream.next().await else {
            panic!("overflow was not reported");
        };
        assert_eq!(dropped.get(), 1);
        let Some(EventDelivery::Event(event)) = stream.next().await else {
            panic!("event after overflow was not delivered");
        };
        assert_eq!(event.id, "after-loss");
    }

    #[tokio::test]
    async fn listener_reports_trailing_loss_without_another_event() {
        let mut listeners = EventListeners::default();
        let (request, mut stream) =
            EventListenerRequest::new::<EventAnimationCanceled>(config(NonZeroUsize::MIN));
        listeners.add_listener(request);

        listeners.start_send(event("retained"));
        listeners.start_send(event("dropped"));

        let Some(EventDelivery::Event(event)) = stream.next().await else {
            panic!("retained event was not delivered");
        };
        assert_eq!(event.id, "retained");
        let Some(EventDelivery::Lagged { dropped }) = stream.next().await else {
            panic!("trailing overflow was not reported");
        };
        assert_eq!(dropped.get(), 1);
    }

    #[tokio::test]
    async fn listener_removes_closed_stream() {
        let mut listeners = EventListeners::default();
        let (request, stream) =
            EventListenerRequest::new::<EventAnimationCanceled>(config(NonZeroUsize::MIN));
        let method = EventAnimationCanceled::method_id();
        listeners.add_listener(request);
        drop(stream);

        listeners.start_send(event("ignored"));
        listeners.prune_closed();

        assert!(!listeners.listeners.contains_key(&method));
    }

    #[tokio::test]
    async fn listener_prunes_closed_stream_without_another_event() {
        let mut listeners = EventListeners::default();
        let (request, stream) =
            EventListenerRequest::new::<EventAnimationCanceled>(config(NonZeroUsize::MIN));
        let method = EventAnimationCanceled::method_id();
        listeners.add_listener(request);
        drop(stream);

        listeners.prune_closed();

        assert!(!listeners.listeners.contains_key(&method));
    }

    #[tokio::test]
    async fn listener_preserves_retained_event_order() {
        let mut listeners = EventListeners::default();
        let (request, mut stream) = EventListenerRequest::new::<EventAnimationCanceled>(config(
            NonZeroUsize::new(3).expect("test capacity is non-zero"),
        ));
        listeners.add_listener(request);

        listeners.start_send(event("first"));
        listeners.start_send(event("second"));
        listeners.start_send(event("third"));
        listeners.start_send(event("dropped"));

        let mut ids = Vec::new();
        for _ in 0..3 {
            let Some(EventDelivery::Event(event)) = stream.next().await else {
                panic!("retained event was not delivered");
            };
            ids.push(event.id.clone());
        }
        assert_eq!(ids, ["first", "second", "third"]);
    }
}
