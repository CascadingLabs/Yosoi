use std::{fmt, net::IpAddr};

use serde::{Deserialize, Serialize};

use crate::internal::policy::PolicyError;

/// Address family permitted for outbound TCP connections.
///
/// With an external proxy this constrains the proxy connection, not the
/// proxy's destination DNS or egress. Strict choices prohibit cross-family fallback.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum IpFamily {
    /// Retain the operating system's available address families.
    #[default]
    SystemDefault,
    /// Connect only to IPv4 addresses.
    Ipv4Only,
    /// Connect only to IPv6 addresses.
    Ipv6Only,
}

impl IpFamily {
    pub(crate) const fn permits(self, address: IpAddr) -> bool {
        match self {
            Self::SystemDefault => true,
            Self::Ipv4Only => address.is_ipv4(),
            Self::Ipv6Only => matches!(address, IpAddr::V6(ip) if ip.to_ipv4_mapped().is_none()),
        }
    }
}

/// Opt-in TCP routing shared by Requests and owned browser Sessions.
///
/// The default preserves existing transport behavior. Explicit routing uses an
/// owned local SOCKS5 tunnel for web traffic, without decrypting destination TLS.
/// This is not an operating-system firewall or an all-protocol egress guarantee.
/// Proxy credentials are present in serialized policy and must be treated as
/// secrets; Debug output redacts the entire proxy URL.
#[derive(Clone, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Network {
    /// Family for TCP connections to a destination or configured upstream proxy.
    #[serde(default)]
    pub ip_family: IpFamily,
    /// Optional already-assigned local IP for destination or upstream-proxy sockets.
    /// This does not allocate an address or choose the public address after NAT.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_address: Option<IpAddr>,
    /// External HTTP CONNECT or SOCKS5 proxy URL, optionally with user/password.
    /// Supported schemes are `http`, `https`, `socks5`, and `socks5h`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub proxy: Option<String>,
}

impl fmt::Debug for Network {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Network")
            .field("ip_family", &self.ip_family)
            .field("source_address", &self.source_address)
            .field("proxy", &self.proxy.as_ref().map(|_| "[redacted]"))
            .finish()
    }
}

impl Network {
    /// Whether transport behavior is unchanged from the package default.
    pub(crate) fn is_default(&self) -> bool {
        self == &Self::default()
    }

    /// Validates family/source agreement and supported proxy URL syntax.
    ///
    /// Address availability, DNS, route, and proxy authentication failures are
    /// observed during acquisition. Validation never contacts the network.
    pub(crate) fn validate(&self) -> Result<(), PolicyError> {
        if self
            .source_address
            .is_some_and(|ip| !self.ip_family.permits(ip))
        {
            return Err(PolicyError::NetworkSourceFamilyMismatch);
        }
        if let Some(proxy) = &self.proxy {
            let parsed = url::Url::parse(proxy).map_err(|_| PolicyError::InvalidProxyUrl)?;
            if !matches!(parsed.scheme(), "http" | "https" | "socks5" | "socks5h")
                || parsed.host_str().is_none()
                || parsed
                    .port_or_known_default()
                    .or_else(|| matches!(parsed.scheme(), "socks5" | "socks5h").then_some(1080))
                    .is_none()
                || parsed.path() != "/" && !parsed.path().is_empty()
                || parsed.query().is_some()
                || parsed.fragment().is_some()
            {
                return Err(PolicyError::InvalidProxyUrl);
            }
        }
        Ok(())
    }
}
