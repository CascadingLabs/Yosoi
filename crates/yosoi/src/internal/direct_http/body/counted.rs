use std::{
    pin::Pin,
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    task::{Context, Poll},
};

pub(super) struct CountedStream<S> {
    inner: S,
    limit: u64,
    pub(super) count: Arc<AtomicU64>,
    pub(super) exceeded: Arc<AtomicBool>,
    pub(super) transport_failed: Arc<AtomicBool>,
    done: bool,
}
impl<S> CountedStream<S> {
    pub(super) fn new(inner: S, limit: u64) -> Self {
        Self {
            inner,
            limit,
            count: Arc::new(AtomicU64::new(0)),
            exceeded: Arc::new(AtomicBool::new(false)),
            transport_failed: Arc::new(AtomicBool::new(false)),
            done: false,
        }
    }
}
impl<S, B, E> futures_util::Stream for CountedStream<S>
where
    S: futures_util::Stream<Item = Result<B, E>> + Unpin,
    B: AsRef<[u8]>,
{
    type Item = Result<bytes::Bytes, E>;
    fn poll_next(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        if self.done {
            return Poll::Ready(None);
        }
        match Pin::new(&mut self.inner).poll_next(cx) {
            Poll::Ready(Some(Ok(chunk))) => {
                let old = self.count.load(Ordering::Relaxed);
                let bytes = chunk.as_ref();
                let accepted = usize::try_from(self.limit.saturating_sub(old))
                    .unwrap_or(usize::MAX)
                    .min(bytes.len());
                let accepted_u64 = u64::try_from(accepted).unwrap_or(u64::MAX);
                let over_limit = accepted < bytes.len();
                let observed = accepted_u64.saturating_add(u64::from(over_limit));
                self.count
                    .store(old.saturating_add(observed), Ordering::Relaxed);
                if over_limit {
                    self.exceeded.store(true, Ordering::Relaxed);
                    self.done = true;
                }
                Poll::Ready(Some(Ok(bytes::Bytes::copy_from_slice(
                    bytes.get(..accepted).unwrap_or_default(),
                ))))
            }
            Poll::Ready(Some(Err(error))) => {
                self.transport_failed.store(true, Ordering::Relaxed);
                self.done = true;
                Poll::Ready(Some(Err(error)))
            }
            Poll::Ready(None) => {
                self.done = true;
                Poll::Ready(None)
            }
            Poll::Pending => Poll::Pending,
        }
    }
}

#[cfg(test)]
#[allow(
    clippy::absolute_paths,
    clippy::arithmetic_side_effects,
    clippy::expect_used,
    clippy::unwrap_used
)]
mod tests {
    use std::{io, sync::atomic::Ordering};

    use futures_util::{StreamExt, stream};

    use super::CountedStream;

    #[tokio::test]
    async fn exact_limit_probes_eof_without_exceeding() {
        let mut counted = CountedStream::new(stream::iter([Ok::<_, io::Error>(b"abc")]), 3);
        assert_eq!(
            counted.next().await.transpose().unwrap(),
            Some(bytes::Bytes::from_static(b"abc"))
        );
        assert_eq!(counted.next().await.transpose().unwrap(), None);
        assert_eq!(counted.count.load(Ordering::Relaxed), 3);
        assert!(!counted.exceeded.load(Ordering::Relaxed));
    }

    #[tokio::test]
    async fn one_over_returns_only_the_bounded_prefix_and_counts_probe() {
        let mut counted = CountedStream::new(stream::iter([Ok::<_, io::Error>(b"abcd")]), 3);
        assert_eq!(
            counted.next().await.transpose().unwrap(),
            Some(bytes::Bytes::from_static(b"abc"))
        );
        assert_eq!(counted.next().await.transpose().unwrap(), None);
        assert_eq!(counted.count.load(Ordering::Relaxed), 4);
        assert!(counted.exceeded.load(Ordering::Relaxed));
    }

    #[tokio::test]
    async fn multi_chunk_count_stops_at_one_over() {
        let chunks = [
            Ok::<_, io::Error>(b"ab".as_slice()),
            Ok::<_, io::Error>(b"cde".as_slice()),
        ];
        let mut counted = CountedStream::new(stream::iter(chunks), 4);
        assert_eq!(
            counted.next().await.transpose().unwrap(),
            Some(bytes::Bytes::from_static(b"ab"))
        );
        assert_eq!(
            counted.next().await.transpose().unwrap(),
            Some(bytes::Bytes::from_static(b"cd"))
        );
        assert_eq!(counted.count.load(Ordering::Relaxed), 5);
        assert!(counted.exceeded.load(Ordering::Relaxed));
    }

    #[tokio::test]
    async fn transport_error_is_forwarded_and_recorded() {
        let source = stream::iter([Err::<&'static [u8], _>(io::Error::other("broken"))]);
        let mut counted = CountedStream::new(source, 4);
        assert!(counted.next().await.expect("one stream item").is_err());
        assert_eq!(counted.count.load(Ordering::Relaxed), 0);
        assert!(counted.transport_failed.load(Ordering::Relaxed));
    }
}
