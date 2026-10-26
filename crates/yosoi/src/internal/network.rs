//! Owned TCP web tunnel. Destination TLS stays between the SDK/browser and site.
use std::{
    io,
    net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr},
    sync::Arc,
    time::Duration,
};

use base64::{Engine as _, engine::general_purpose::STANDARD};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpSocket, TcpStream, lookup_host},
    task::{JoinHandle, JoinSet},
};
use tokio_util::sync::CancellationToken;

use crate::internal::policy::policy::{IpFamily, Network};
use rustls::{ClientConfig, crypto::ring, pki_types::ServerName};
use rustls_platform_verifier::BuilderVerifierExt as _;
use tokio::io::{AsyncRead, AsyncWrite, copy_bidirectional};
use tokio::time::timeout;

trait ProxyStream: AsyncRead + AsyncWrite + Send + Unpin {}
impl<T: AsyncRead + AsyncWrite + Send + Unpin> ProxyStream for T {}
type Outbound = Box<dyn ProxyStream>;

const MAX_HEAD: usize = 32 * 1024;
const MAX_CONNECTIONS: usize = 64;
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(30);

#[cfg(test)]
#[path = "network/tests.rs"]
mod tests;

#[allow(
    clippy::redundant_pub_crate,
    reason = "the development support crate includes this module publicly; runtime helpers stay crate private"
)]
pub(crate) struct RelayCleanup(Arc<Relay>);
impl Drop for RelayCleanup {
    fn drop(&mut self) {
        self.0.close();
    }
}

#[derive(Debug)]
#[allow(
    clippy::redundant_pub_crate,
    reason = "the development support crate includes this module publicly; runtime helpers stay crate private"
)]
pub(crate) struct Relay {
    address: SocketAddr,
    task: JoinHandle<()>,
    stop: CancellationToken,
    finished: CancellationToken,
}

impl PartialEq for Relay {
    fn eq(&self, other: &Self) -> bool {
        self.address == other.address
    }
}
impl Eq for Relay {}

impl Drop for Relay {
    fn drop(&mut self) {
        self.stop.cancel();
        self.task.abort();
    }
}

impl Relay {
    pub(crate) async fn start(network: &Network) -> io::Result<Arc<Self>> {
        network.validate().map_err(io::Error::other)?;
        // Bind synchronously before reporting readiness. No probes or sleeps.
        if let Some(source) = network.source_address {
            if source.is_unspecified()
                || source.is_multicast()
                || source == IpAddr::V4(Ipv4Addr::BROADCAST)
            {
                return Err(io::Error::new(
                    io::ErrorKind::AddrNotAvailable,
                    "source address must be a concrete unicast address",
                ));
            }
            let socket = if source.is_ipv4() {
                TcpSocket::new_v4()?
            } else {
                TcpSocket::new_v6()?
            };
            socket.bind(SocketAddr::new(source, 0))?;
        }
        let loopback = if network.ip_family == IpFamily::Ipv6Only
            || network.source_address.is_some_and(|ip| ip.is_ipv6())
        {
            IpAddr::V6(Ipv6Addr::LOCALHOST)
        } else {
            IpAddr::V4(Ipv4Addr::LOCALHOST)
        };
        let listener = TcpListener::bind((loopback, 0)).await?;
        let address = listener.local_addr()?;
        let stop = CancellationToken::new();
        let network = network.clone();
        let cancellation = stop.clone();
        let finished = CancellationToken::new();
        let finished_guard = finished.clone().drop_guard();
        let task = tokio::spawn(async move {
            let _finished_guard = finished_guard;
            let mut connections = JoinSet::new();
            loop {
                tokio::select! {
                    biased;
                    () = cancellation.cancelled() => break,
                    _ = connections.join_next(), if !connections.is_empty() => {},
                    accepted = listener.accept(), if connections.len() < MAX_CONNECTIONS => {
                        let Ok((mut stream, _)) = accepted else { break; };
                        let policy = network.clone();
                        connections.spawn(async move {
                            let handshake = timeout(HANDSHAKE_TIMEOUT, establish(&mut stream, &policy)).await;
                            if let Ok(Ok(mut outbound)) = handshake {
                                let _ = copy_bidirectional(&mut stream, &mut outbound).await;
                            }
                        });
                    }
                }
            }
            drop(listener);
            connections.abort_all();
            while connections.join_next().await.is_some() {}
        });
        Ok(Arc::new(Self {
            address,
            task,
            stop,
            finished,
        }))
    }

    pub(crate) const fn address(&self) -> SocketAddr {
        self.address
    }
    pub(crate) fn url(&self) -> String {
        format!("socks5h://{}", self.address)
    }
    pub(crate) fn close(&self) {
        self.stop.cancel();
    }
    pub(crate) async fn shutdown(&self) {
        self.close();
        self.finished.cancelled().await;
    }
    pub(crate) fn cleanup(self: &Arc<Self>) -> RelayCleanup {
        RelayCleanup(Arc::clone(self))
    }
}

fn invalid() -> io::Error {
    io::Error::new(
        io::ErrorKind::InvalidInput,
        "invalid proxy protocol or destination",
    )
}

async fn read_head<S: AsyncRead + Unpin + ?Sized>(
    stream: &mut S,
) -> io::Result<(Vec<u8>, Vec<u8>)> {
    let mut bytes = Vec::new();
    let mut buffer = [0; 4096];
    loop {
        if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
            let end = end.checked_add(4).ok_or_else(invalid)?;
            if end > MAX_HEAD {
                return Err(invalid());
            }
            let tail = bytes.get(end..).ok_or_else(invalid)?.to_vec();
            bytes.truncate(end);
            return Ok((bytes, tail));
        }
        if bytes.len() >= MAX_HEAD {
            return Err(invalid());
        }
        let n = stream.read(&mut buffer).await?;
        if n == 0 {
            return Err(io::Error::from(io::ErrorKind::UnexpectedEof));
        }
        bytes.extend_from_slice(buffer.get(..n).ok_or_else(invalid)?);
    }
}

async fn establish(stream: &mut TcpStream, policy: &Network) -> io::Result<Outbound> {
    if stream.read_u8().await? != 5 {
        return Err(invalid());
    }
    let mut methods = vec![0; usize::from(stream.read_u8().await?)];
    stream.read_exact(&mut methods).await?;
    if !methods.contains(&0) {
        stream.write_all(&[5, 255]).await?;
        return Err(invalid());
    }
    stream.write_all(&[5, 0]).await?;
    let mut command = [0; 4];
    stream.read_exact(&mut command).await?;
    let [5, 1, 0, kind] = command else {
        return Err(invalid());
    };
    let destination = match kind {
        1 => {
            let mut ip = [0; 4];
            stream.read_exact(&mut ip).await?;
            Ipv4Addr::from(ip).to_string()
        }
        4 => {
            let mut ip = [0; 16];
            stream.read_exact(&mut ip).await?;
            Ipv6Addr::from(ip).to_string()
        }
        3 => {
            let length = usize::from(stream.read_u8().await?);
            if length == 0 {
                return Err(invalid());
            }
            let mut name = vec![0; length];
            stream.read_exact(&mut name).await?;
            String::from_utf8(name).map_err(|_| invalid())?
        }
        _ => return Err(invalid()),
    };
    let port = stream.read_u16().await?;
    let outbound = match connect_route(policy, &destination, port).await {
        Ok(outbound) => outbound,
        Err(error) => {
            let reason = match error.kind() {
                io::ErrorKind::PermissionDenied => 2,
                io::ErrorKind::NetworkUnreachable => 3,
                io::ErrorKind::AddrNotAvailable => 4,
                io::ErrorKind::ConnectionRefused => 5,
                io::ErrorKind::TimedOut => 6,
                _ => 1,
            };
            // A protocol failure prevents Chrome from waiting/retrying a silent
            // HTTP disconnect, and never fabricates an origin HTTP response.
            stream
                .write_all(&[5, reason, 0, 1, 0, 0, 0, 0, 0, 0])
                .await?;
            return Err(error);
        }
    };
    stream.write_all(&[5, 0, 0, 1, 0, 0, 0, 0, 0, 0]).await?;
    Ok(outbound)
}

fn host(url: &url::Url) -> io::Result<String> {
    match url.host().ok_or_else(invalid)? {
        url::Host::Domain(s) => Ok(s.to_owned()),
        url::Host::Ipv4(ip) => Ok(ip.to_string()),
        url::Host::Ipv6(ip) => Ok(ip.to_string()),
    }
}

async fn connect_socket(policy: &Network, host: &str, port: u16) -> io::Result<TcpStream> {
    let mut last = io::Error::new(
        io::ErrorKind::AddrNotAvailable,
        "no address satisfies network policy",
    );
    for address in lookup_host((host, port)).await? {
        if !policy.ip_family.permits(address.ip())
            || policy
                .source_address
                .is_some_and(|source| source.is_ipv4() != address.is_ipv4())
        {
            continue;
        }
        let socket = if address.is_ipv4() {
            TcpSocket::new_v4()?
        } else {
            TcpSocket::new_v6()?
        };
        if let Some(source) = policy.source_address {
            socket.bind(SocketAddr::new(source, 0))?;
        }
        match socket.connect(address).await {
            Ok(stream) => return Ok(stream),
            Err(error) => last = error,
        }
    }
    Err(last)
}

async fn connect_route(policy: &Network, destination: &str, port: u16) -> io::Result<Outbound> {
    let Some(proxy) = &policy.proxy else {
        return Ok(Box::new(connect_socket(policy, destination, port).await?));
    };
    let proxy = url::Url::parse(proxy).map_err(|_| invalid())?;
    let proxy_host = host(&proxy)?;
    let proxy_port = proxy.port_or_known_default().unwrap_or(1080);
    let stream = connect_socket(policy, &proxy_host, proxy_port).await?;
    let mut stream: Outbound = if proxy.scheme() == "https" {
        let provider = Arc::new(ring::default_provider());
        let config = ClientConfig::builder_with_provider(provider)
            .with_safe_default_protocol_versions()
            .map_err(io::Error::other)?
            .with_platform_verifier()
            .map_err(io::Error::other)?
            .with_no_client_auth();
        let server_name = ServerName::try_from(proxy_host.clone()).map_err(|_| invalid())?;
        Box::new(
            tokio_rustls::TlsConnector::from(Arc::new(config))
                .connect(server_name, stream)
                .await?,
        )
    } else {
        Box::new(stream)
    };
    let user = percent_encoding::percent_decode_str(proxy.username())
        .decode_utf8()
        .map_err(|_| invalid())?;
    let password = percent_encoding::percent_decode_str(proxy.password().unwrap_or(""))
        .decode_utf8()
        .map_err(|_| invalid())?;
    if matches!(proxy.scheme(), "http" | "https") {
        let authority = if destination.contains(':') {
            format!("[{destination}]:{port}")
        } else {
            format!("{destination}:{port}")
        };
        let auth = if user.is_empty() && proxy.password().is_none() {
            String::new()
        } else {
            format!(
                "Proxy-Authorization: Basic {}\r\n",
                STANDARD.encode(format!("{user}:{password}"))
            )
        };
        stream
            .write_all(
                format!("CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n{auth}\r\n")
                    .as_bytes(),
            )
            .await?;
        let (head, tail) = read_head(&mut stream).await?;
        let mut headers = [httparse::EMPTY_HEADER; 128];
        let mut response = httparse::Response::new(&mut headers);
        response.parse(&head).map_err(|_| invalid())?;
        if response.code != Some(200) || !tail.is_empty() {
            return Err(io::Error::new(
                io::ErrorKind::ConnectionRefused,
                "upstream proxy rejected CONNECT",
            ));
        }
    } else {
        let credentials = !user.is_empty() || proxy.password().is_some();
        stream
            .write_all(if credentials { &[5, 1, 2] } else { &[5, 1, 0] })
            .await?;
        let mut reply = [0; 2];
        stream.read_exact(&mut reply).await?;
        if reply != [5, if credentials { 2 } else { 0 }] {
            return Err(invalid());
        }
        if credentials {
            let mut auth = vec![1, u8::try_from(user.len()).map_err(|_| invalid())?];
            auth.extend_from_slice(user.as_bytes());
            auth.push(u8::try_from(password.len()).map_err(|_| invalid())?);
            auth.extend_from_slice(password.as_bytes());
            stream.write_all(&auth).await?;
            stream.read_exact(&mut reply).await?;
            if reply != [1, 0] {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "upstream proxy authentication failed",
                ));
            }
        }
        let mut command = vec![5, 1, 0];
        // socks5 resolves destinations locally; socks5h delegates their DNS.
        let address = if proxy.scheme() == "socks5" {
            Some(
                lookup_host((destination, port))
                    .await?
                    .next()
                    .ok_or_else(invalid)?
                    .ip(),
            )
        } else {
            destination.parse::<IpAddr>().ok()
        };
        match address {
            Some(IpAddr::V4(ip)) => {
                command.push(1);
                command.extend_from_slice(&ip.octets());
            }
            Some(IpAddr::V6(ip)) => {
                command.push(4);
                command.extend_from_slice(&ip.octets());
            }
            None => {
                command.extend_from_slice(&[
                    3,
                    u8::try_from(destination.len()).map_err(|_| invalid())?,
                ]);
                command.extend_from_slice(destination.as_bytes());
            }
        }
        command.extend_from_slice(&port.to_be_bytes());
        stream.write_all(&command).await?;
        let mut header = [0; 4];
        stream.read_exact(&mut header).await?;
        let [5, 0, 0, kind] = header else {
            return Err(io::Error::new(
                io::ErrorKind::ConnectionRefused,
                "upstream proxy rejected SOCKS connection",
            ));
        };
        let length: usize = match kind {
            1 => 4,
            4 => 16,
            3 => usize::from(stream.read_u8().await?),
            _ => return Err(invalid()),
        };
        let mut discard = vec![0; length.checked_add(2).ok_or_else(invalid)?];
        stream.read_exact(&mut discard).await?;
    }
    Ok(stream)
}
