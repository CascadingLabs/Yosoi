#![allow(
    clippy::panic_in_result_fn,
    reason = "assertions report controlled networking fixture failures"
)]

use super::*;
use crate::internal::policy::{Policy, PolicyError, PolicySnapshot, policy::IpFamily};
use rustls::{
    ServerConfig,
    crypto::ring,
    pki_types::{CertificateDer, PrivateKeyDer},
};
use std::error::Error;
use tokio::time::timeout;

type TestResult = Result<(), Box<dyn Error + Send + Sync>>;

#[test]
fn opt_in_policy_validation_identity_and_redaction() -> TestResult {
    let defaults = Policy::default();
    assert!(!defaults.to_canonical_json()?.contains("network"));
    let mut policy = defaults.clone();
    policy.network.ip_family = IpFamily::Ipv6Only;
    assert_ne!(defaults.effective_identity()?, policy.effective_identity()?);
    let snapshot = PolicySnapshot::from_policy(&policy)?;
    policy.network.ip_family = IpFamily::Ipv4Only;
    assert_eq!(snapshot.policy().network.ip_family, IpFamily::Ipv6Only);
    policy.network.source_address = Some("::1".parse()?);
    assert!(policy.validate().is_err());
    policy.network.source_address = None;
    for proxy in [
        "ftp://proxy.example",
        "http://proxy.example/path",
        "http://proxy.example/?query",
        "invalid",
    ] {
        policy.network.proxy = Some(proxy.to_owned());
        assert!(policy.validate().is_err());
    }
    policy.network.proxy = Some("http://user:super-secret@proxy.example:8080".to_owned());
    policy.validate()?;
    assert!(!format!("{policy:?}").contains("super-secret"));
    assert!(policy.to_canonical_json()?.contains("super-secret"));
    let decoded: Policy = serde_json::from_str(&policy.to_canonical_json()?)?;
    assert_eq!(decoded, policy);
    for identity in [
        policy.archived_v2_identity(),
        policy.archived_v3_map_identity(),
        policy.archived_v3_map_pre_robots_identity(),
        policy.archived_v5_identity(),
        policy.archived_v6_identity(),
        policy
            .effective_policy()?
            .archived_v4_search_pre_robots_identity(),
        policy.effective_policy()?.archived_v5_identity(),
        policy.effective_policy()?.archived_v6_identity(),
    ] {
        assert_eq!(identity, Err(PolicyError::ArchivedIdentityMismatch));
    }
    Ok(())
}

#[tokio::test]
async fn opt_in_policy_archive_reopens_with_the_same_route_and_identity() -> TestResult {
    use crate::internal::archive::Archive;

    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("archive");
    let policy = Policy {
        network: Network {
            ip_family: IpFamily::Ipv6Only,
            source_address: Some("::1".parse()?),
            proxy: Some("socks5h://user:secret@[::1]:1080".to_owned()),
        },
        ..Policy::default()
    };
    let identity = policy.effective_identity()?;
    let archive = Archive::open(&root).await?;
    let reference = archive.write(&policy).await?;
    drop(archive);
    let reopened = Archive::open(&root).await?;
    let restored = reopened.read(&reference).await?;
    assert_eq!(restored.network, policy.network);
    assert_eq!(restored.effective_identity()?, identity);
    Ok(())
}

async fn echo_listener(
    address: &str,
) -> io::Result<(SocketAddr, JoinHandle<io::Result<SocketAddr>>)> {
    let listener = TcpListener::bind(address).await?;
    let address = listener.local_addr()?;
    let task = tokio::spawn(async move {
        let (mut socket, peer) = listener.accept().await?;
        let mut message = [0; 4];
        socket.read_exact(&mut message).await?;
        socket.write_all(&message).await?;
        Ok(peer)
    });
    Ok((address, task))
}

#[tokio::test]
async fn ipv4_and_ipv6_socks_tunnels_bind_the_observed_source() -> TestResult {
    for (bind, family, source) in [
        ("127.0.0.1:0", IpFamily::Ipv4Only, "127.0.0.1"),
        ("[::1]:0", IpFamily::Ipv6Only, "::1"),
    ] {
        let (address, server) = echo_listener(bind).await?;
        let network = Network {
            ip_family: family,
            source_address: Some(source.parse()?),
            proxy: None,
        };
        let relay = Relay::start(&network).await?;
        let mut client = TcpStream::connect(relay.address()).await?;
        client.write_all(&[5, 1, 0]).await?;
        let mut greeting = [0; 2];
        client.read_exact(&mut greeting).await?;
        assert_eq!(greeting, [5, 0]);
        let mut command = vec![5, 1, 0];
        match address.ip() {
            IpAddr::V4(ip) => {
                command.push(1);
                command.extend_from_slice(&ip.octets());
            }
            IpAddr::V6(ip) => {
                command.push(4);
                command.extend_from_slice(&ip.octets());
            }
        }
        command.extend_from_slice(&address.port().to_be_bytes());
        client.write_all(&command).await?;
        let mut connected = [0; 10];
        client.read_exact(&mut connected).await?;
        assert_eq!(connected, [5, 0, 0, 1, 0, 0, 0, 0, 0, 0]);
        client.write_all(b"ping").await?;
        let mut echoed = [0; 4];
        client.read_exact(&mut echoed).await?;
        assert_eq!(&echoed, b"ping");
        let peer = server.await??;
        assert_eq!(peer.ip(), source.parse::<IpAddr>()?);
        relay.close();
    }
    Ok(())
}

#[tokio::test]
async fn forbidden_literal_and_dns_addresses_never_connect() -> TestResult {
    let ipv4 = Network {
        ip_family: IpFamily::Ipv4Only,
        ..Network::default()
    };
    assert!(connect_socket(&ipv4, "::1", 80).await.is_err());
    let ipv6 = Network {
        ip_family: IpFamily::Ipv6Only,
        ..Network::default()
    };
    assert!(connect_socket(&ipv6, "127.0.0.1", 80).await.is_err());
    assert!(connect_socket(&ipv6, "::ffff:127.0.0.1", 80).await.is_err());
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let mut stream = connect_socket(&ipv4, "localhost", listener.local_addr()?.port()).await?;
    let (mut accepted, peer) = listener.accept().await?;
    assert!(peer.is_ipv4());
    stream.write_all(b"x").await?;
    assert_eq!(accepted.read_u8().await?, b'x');
    Ok(())
}

#[tokio::test]
async fn unavailable_source_fails_before_the_helper_is_admitted() -> TestResult {
    let policy = Network {
        ip_family: IpFamily::Ipv6Only,
        source_address: Some("2001:db8::f00d".parse()?),
        proxy: None,
    };
    assert!(Relay::start(&policy).await.is_err());
    Ok(())
}

#[tokio::test]
async fn wildcard_and_multicast_sources_do_not_silently_select_another_address() -> TestResult {
    for source in ["0.0.0.0", "::", "224.0.0.1", "ff02::1", "255.255.255.255"] {
        let policy = Network {
            source_address: Some(source.parse()?),
            ..Network::default()
        };
        assert!(Relay::start(&policy).await.is_err());
    }
    Ok(())
}

#[tokio::test]
async fn http_upstream_uses_decoded_basic_auth_without_leaking_to_origin() -> TestResult {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let server = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await?;
        let (head, _) = read_head(&mut socket).await?;
        let head = String::from_utf8(head).map_err(io::Error::other)?;
        assert!(head.starts_with("CONNECT example.test:443 HTTP/1.1"));
        assert!(head.contains(&format!(
            "Proxy-Authorization: Basic {}",
            STANDARD.encode("user:p@ss")
        )));
        socket
            .write_all(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            .await?;
        let mut bytes = [0; 4];
        socket.read_exact(&mut bytes).await?;
        assert_eq!(&bytes, b"ping");
        Ok::<_, io::Error>(())
    });
    let network = Network {
        proxy: Some(format!("http://user:p%40ss@{address}")),
        ..Network::default()
    };
    let mut stream = connect_route(&network, "example.test", 443).await?;
    stream.write_all(b"ping").await?;
    server.await??;
    Ok(())
}

#[tokio::test]
async fn socks5h_delegates_hostname_and_authenticates() -> TestResult {
    let listener = TcpListener::bind("[::1]:0").await?;
    let address = listener.local_addr()?;
    let server = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await?;
        let mut greeting = [0; 3];
        socket.read_exact(&mut greeting).await?;
        assert_eq!(greeting, [5, 1, 2]);
        socket.write_all(&[5, 2]).await?;
        assert_eq!(socket.read_u8().await?, 1);
        let mut user = vec![0; usize::from(socket.read_u8().await?)];
        socket.read_exact(&mut user).await?;
        let mut password = vec![0; usize::from(socket.read_u8().await?)];
        socket.read_exact(&mut password).await?;
        assert_eq!(user, b"user");
        assert_eq!(password, b"secret");
        socket.write_all(&[1, 0]).await?;
        let mut header = [0; 4];
        socket.read_exact(&mut header).await?;
        assert_eq!(header, [5, 1, 0, 3]);
        let mut host = vec![0; usize::from(socket.read_u8().await?)];
        socket.read_exact(&mut host).await?;
        assert_eq!(host, b"unresolvable.invalid");
        assert_eq!(socket.read_u16().await?, 443);
        socket.write_all(&[5, 0, 0, 4]).await?;
        socket.write_all(&[0; 18]).await?;
        Ok::<_, io::Error>(())
    });
    let network = Network {
        ip_family: IpFamily::Ipv6Only,
        proxy: Some(format!("socks5h://user:secret@{address}")),
        ..Network::default()
    };
    let _stream = connect_route(&network, "unresolvable.invalid", 443).await?;
    server.await??;
    Ok(())
}

#[tokio::test]
async fn https_upstream_rejects_an_untrusted_certificate() -> TestResult {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let cert = CertificateDer::from(
        include_bytes!("../direct_http/tests/fixtures/direct-http-tls/cert.der").to_vec(),
    );
    let key = PrivateKeyDer::try_from(
        include_bytes!("../direct_http/tests/fixtures/direct-http-tls/key.der").to_vec(),
    )?;
    let config = ServerConfig::builder_with_provider(Arc::new(ring::default_provider()))
        .with_safe_default_protocol_versions()?
        .with_no_client_auth()
        .with_single_cert(vec![cert], key)?;
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await?;
        let result = tokio_rustls::TlsAcceptor::from(Arc::new(config))
            .accept(stream)
            .await;
        assert!(result.is_err());
        Ok::<_, io::Error>(())
    });
    let network = Network {
        proxy: Some(format!("https://{address}")),
        ..Network::default()
    };
    assert!(connect_route(&network, "example.test", 443).await.is_err());
    server.await??;
    Ok(())
}

#[tokio::test]
async fn socks5_resolves_locally_and_uses_unauthenticated_ip_command() -> TestResult {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let server = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await?;
        let mut greeting = [0; 3];
        socket.read_exact(&mut greeting).await?;
        assert_eq!(greeting, [5, 1, 0]);
        socket.write_all(&[5, 0]).await?;
        let mut header = [0; 4];
        socket.read_exact(&mut header).await?;
        assert_eq!(header, [5, 1, 0, 1]);
        let mut destination = [0; 4];
        socket.read_exact(&mut destination).await?;
        assert_eq!(destination, [127, 0, 0, 1]);
        assert_eq!(socket.read_u16().await?, 8080);
        socket.write_all(&[5, 0, 0, 1, 127, 0, 0, 1, 0, 0]).await?;
        Ok::<_, io::Error>(())
    });
    let network = Network {
        proxy: Some(format!("socks5://{address}")),
        ..Network::default()
    };
    let _stream = connect_route(&network, "127.0.0.1", 8080).await?;
    server.await??;
    Ok(())
}

#[tokio::test]
async fn close_cancels_active_tunnels_and_drops_listener() -> TestResult {
    let relay = Relay::start(&Network::default()).await?;
    let address = relay.address();
    let mut connection = TcpStream::connect(address).await?;
    relay.shutdown().await;
    let mut byte = [0];
    let read = timeout(Duration::from_secs(2), connection.read(&mut byte)).await?;
    assert!(matches!(read, Ok(0) | Err(_)));
    assert!(TcpStream::connect(address).await.is_err());
    Ok(())
}
