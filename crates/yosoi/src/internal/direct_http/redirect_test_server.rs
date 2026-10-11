use std::{sync::Arc, time::Duration};

use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    sync::{Mutex, oneshot},
    time::sleep,
};

pub(super) async fn server(routes: Vec<(&'static str, Duration)>) -> String {
    server_with_request_signal(routes, None).await.0
}

pub(super) async fn server_observing_request(
    routes: Vec<(&'static str, Duration)>,
    request_target: &'static str,
) -> (String, oneshot::Receiver<()>, oneshot::Sender<()>) {
    let (url, signal, release) = server_with_request_signal(routes, Some(request_target)).await;
    (url, signal.unwrap(), release.unwrap())
}

async fn server_with_request_signal(
    routes: Vec<(&'static str, Duration)>,
    observed_target: Option<&'static str>,
) -> (
    String,
    Option<oneshot::Receiver<()>>,
    Option<oneshot::Sender<()>>,
) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let routes = Arc::new(Mutex::new(routes.into_iter()));
    let observer = observed_target.map(|_| {
        let (request_sender, request_receiver) = oneshot::channel();
        let (release_sender, release_receiver) = oneshot::channel();
        (
            Arc::new(Mutex::new(Some(request_sender))),
            request_receiver,
            release_sender,
            Arc::new(Mutex::new(Some(release_receiver))),
        )
    });
    let observer_sender = observer
        .as_ref()
        .map(|(sender, _, _, _)| Arc::clone(sender));
    let release_receiver = observer
        .as_ref()
        .map(|(_, _, _, receiver)| Arc::clone(receiver));
    tokio::spawn(async move {
        loop {
            let Ok((mut stream, _)) = listener.accept().await else {
                return;
            };
            let routes = Arc::clone(&routes);
            let observer_sender = observer_sender.as_ref().map(Arc::clone);
            let release_receiver = release_receiver.as_ref().map(Arc::clone);
            tokio::spawn(async move {
                let mut request = [0_u8; 2048];
                let mut used = 0_usize;
                while used < request.len() {
                    let Some(remaining) = request.get_mut(used..) else {
                        break;
                    };
                    let Ok(read) = stream.read(remaining).await else {
                        break;
                    };
                    if read == 0 {
                        break;
                    }
                    used = used.saturating_add(read);
                    if request
                        .get(..used)
                        .is_some_and(|bytes| bytes.windows(2).any(|window| window == b"\r\n"))
                    {
                        break;
                    }
                }
                let observed = observed_target.is_some_and(|target| {
                    String::from_utf8_lossy(request.get(..used).unwrap_or_default())
                        .contains(target)
                });
                if observed {
                    let sender = match &observer_sender {
                        Some(sender) => sender.lock().await.take(),
                        None => None,
                    };
                    if let Some(sender) = sender {
                        let _ = sender.send(());
                    }
                    let release = match &release_receiver {
                        Some(receiver) => receiver.lock().await.take(),
                        None => None,
                    };
                    if let Some(release) = release {
                        let _ = release.await;
                    }
                }
                let next = routes.lock().await.next();
                if let Some((response, delay)) = next {
                    sleep(delay).await;
                    let _ = stream.write_all(response.as_bytes()).await;
                }
            });
        }
    });
    let url = format!("http://{address}/start?signature=INITIAL_SECRET#initial");
    let (request_signal, response_release) = observer
        .map_or((None, None), |(_, receiver, sender, _)| {
            (Some(receiver), Some(sender))
        });
    (url, request_signal, response_release)
}
