use crate::internal::engine::execution::{ExecutionPool, ExecutionPoolError};
use std::future as std_future;
use std::{future::Future, task::Poll};

#[tokio::test]
async fn bounded_queue_and_cancelled_waiter_return_capacity() {
    let pool = ExecutionPool::new(1, 1).expect("fixture pool");
    let held = pool.acquire().await.expect("first permit");
    let mut waiting = Box::pin(pool.acquire());
    std_future::poll_fn(|cx| {
        assert!(matches!(waiting.as_mut().poll(cx), Poll::Pending));
        Poll::Ready(())
    })
    .await;
    assert_eq!(pool.snapshot().queued, 1);
    assert!(matches!(
        pool.acquire().await,
        Err(ExecutionPoolError::QueueFull)
    ));
    drop(waiting);
    assert_eq!(pool.snapshot().queued, 0);
    drop(held);
    let next = pool.acquire().await.expect("returned capacity");
    assert_eq!(pool.snapshot().active, 1);
    drop(next);
    assert_eq!(pool.snapshot().active, 0);
    assert_eq!(pool.snapshot().peak_active, 1);
}

#[tokio::test]
async fn admission_is_fifo_without_binding_workers_to_tabs() {
    let pool = ExecutionPool::new(1, 2).expect("fixture pool");
    let held = pool.acquire().await.expect("held capacity");
    let mut first = Box::pin(pool.acquire());
    let mut second = Box::pin(pool.acquire());
    std_future::poll_fn(|cx| {
        assert!(matches!(first.as_mut().poll(cx), Poll::Pending));
        assert!(matches!(second.as_mut().poll(cx), Poll::Pending));
        Poll::Ready(())
    })
    .await;
    drop(held);
    std_future::poll_fn(|cx| {
        assert!(matches!(second.as_mut().poll(cx), Poll::Pending));
        Poll::Ready(())
    })
    .await;
    let first_permit = first.await.expect("first FIFO waiter");
    assert_eq!(pool.snapshot().active, 1);
    drop(first_permit);
    let second_permit = second.await.expect("second FIFO waiter");
    drop(second_permit);
    assert_eq!(pool.snapshot().active, 0);
    assert_eq!(pool.snapshot().queued, 0);
}

#[test]
fn parking_is_independent_of_execution_capacity() {
    let pool = ExecutionPool::new(2, 2).expect("fixture pool");
    let parked = pool.park();
    assert_eq!(pool.snapshot().parked, 1);
    assert_eq!(pool.snapshot().active, 0);
    drop(parked);
    assert_eq!(pool.snapshot().parked, 0);
    assert_eq!(pool.snapshot().waiting, 0);
    assert!(ExecutionPool::new(0, 2).is_err());
}
