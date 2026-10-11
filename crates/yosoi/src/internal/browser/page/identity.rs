use super::Page;
use crate::internal::browser::error::Result;
use crate::internal::browser::error::VoidCrawlError;
use crate::internal::browser::stealth::NavigatorWebdriverPolicy;
use crate::internal::browser::stealth::StealthConfig;
use crate::internal::browser::viewport::Viewport;
use chromiumoxide::Page as CdpPage;
use chromiumoxide::cdp::browser_protocol::browser::GetVersionParams;
use chromiumoxide::cdp::browser_protocol::emulation::SetUserAgentOverrideParams;
use chromiumoxide::cdp::browser_protocol::emulation::UserAgentBrandVersion;
use chromiumoxide::cdp::browser_protocol::emulation::UserAgentMetadata;
use chromiumoxide::cdp::browser_protocol::page::AddScriptToEvaluateOnNewDocumentParams;
use std::fs;
use std::sync::atomic::Ordering;

struct BrowserIdentityProbe {
    user_agent: String,
    platform: String,
    metadata: Option<UserAgentMetadata>,
}

/// Read Chrome's exact product and native User-Agent before the headless-token
/// override. `Browser.getVersion` is origin-independent, unlike Client Hints
/// on the initial `about:blank` document.
async fn probe_browser_identity(page: &CdpPage) -> Result<BrowserIdentityProbe> {
    let version = page
        .execute(GetVersionParams::default())
        .await
        .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
        .result;
    let full_version = version
        .product
        .split_once('/')
        .map(|(_, value)| value)
        .filter(|value| !value.is_empty());
    let (platform, metadata) =
        client_hints_for_ua_with_full_version(&version.user_agent, full_version);
    Ok(BrowserIdentityProbe {
        user_agent: version.user_agent,
        platform,
        metadata,
    })
}

/// Strip any "Headless" token from a UA. Headless Chrome advertises
/// `HeadlessChrome/<ver>` — an instant bot signal. Rewriting only the
/// `Headless` substring keeps the version accurate (no stale hardcoded UA).
pub(super) fn dehead(ua: &str) -> String {
    if ua.contains("HeadlessChrome") {
        ua.replace("HeadlessChrome", "Chrome")
    } else if ua.contains("Headless") {
        ua.replace("Headless", "")
    } else {
        ua.to_string()
    }
}

/// Derive a coherent `navigator.platform` value and Client-Hints
/// [`UserAgentMetadata`] from a UA string, so the UA, `navigator.platform`,
/// and `navigator.userAgentData` all agree. A mismatch between them (e.g. a
/// Linux UA with `navigator.platform == "Win32"`, or empty `brands`) is a
/// strong bot signal. Best-effort: an unrecognized UA gets a generic
/// Linux/x86_64 identity, and a missing Chrome version yields empty brands
/// rather than a wrong one.
pub(super) fn client_hints_for_ua(ua: &str) -> (String, Option<UserAgentMetadata>) {
    client_hints_for_ua_with_full_version(ua, None)
}

pub(super) fn client_hints_for_ua_with_full_version(
    ua: &str,
    exact_full_version: Option<&str>,
) -> (String, Option<UserAgentMetadata>) {
    // (navigator.platform, Sec-CH-UA-Platform, platformVersion)
    let (nav_platform, ch_platform, platform_version) = if ua.contains("Windows") {
        ("Win32", "Windows", "15.0.0".to_string())
    } else if ua.contains("Mac OS X") || ua.contains("Macintosh") {
        ("MacIntel", "macOS", "14.5.0".to_string())
    } else {
        ("Linux x86_64", "Linux", linux_platform_version())
    };

    // Chrome version from the UA: "…Chrome/148.0.0.0 …" → major "148", full
    // "148.0.0.0". `None` when absent (non-Chrome UA) → no brands.
    let chrome_ver: Option<&str> = ua
        .split("Chrome/")
        .nth(1)
        .and_then(|s| s.split_whitespace().next());
    let major: Option<&str> = chrome_ver.and_then(|v| v.split('.').next());

    let exact_full_version = exact_full_version.or(chrome_ver);
    let mut builder = UserAgentMetadata::builder()
        .platform(ch_platform)
        .platform_version(platform_version)
        .architecture("x86")
        .model("")
        .mobile(false)
        .bitness("64")
        .wow64(false);

    if let (Some(major), Some(full)) = (major, exact_full_version) {
        // Low-entropy `brands` (major only) + `fullVersionList` (full), each
        // with a GREASE entry, mirroring what real Chrome emits.
        builder = builder
            .brands([
                UserAgentBrandVersion::new("Chromium", major),
                UserAgentBrandVersion::new("Google Chrome", major),
                UserAgentBrandVersion::new("Not_A Brand", "24"),
            ])
            .full_version_lists([
                UserAgentBrandVersion::new("Chromium", full),
                UserAgentBrandVersion::new("Google Chrome", full),
                UserAgentBrandVersion::new("Not_A Brand", "24.0.0.0"),
            ]);
    }

    // build() only errors if a mandatory field is unset; platform,
    // platform_version, architecture, model, and mobile are all set above, so
    // this is `Some` in practice. `None` (unreachable) simply skips metadata.
    (nav_platform.to_string(), builder.build().ok())
}

fn linux_platform_version() -> String {
    fs::read_to_string("/proc/sys/kernel/osrelease").map_or_else(
        |_| String::new(),
        |release| {
            release
                .trim()
                .split(['.', '-'])
                .take_while(|component| {
                    !component.is_empty()
                        && component
                            .chars()
                            .all(|character| character.is_ascii_digit())
                })
                .take(3)
                .collect::<Vec<_>>()
                .join(".")
        },
    )
}

/// The mobile counterpart to [`client_hints_for_ua`], used by
/// [`Page::set_viewport`] for device-preset UAs. Real Safari (iPhone/iPad
/// UAs) never sends Client-Hints headers at all, so those get a plain UA
/// override with no fabricated metadata — matching a real device rather
/// than inventing brands Safari itself doesn't have. Chrome-on-Android UAs
/// get `mobile: true` metadata built the same way `client_hints_for_ua`
/// builds it for desktop Chrome.
pub(super) fn mobile_ua_platform_and_metadata(ua: &str) -> (String, Option<UserAgentMetadata>) {
    if ua.contains("iPad") {
        return ("iPad".to_string(), None);
    }
    if ua.contains("iPhone") {
        return ("iPhone".to_string(), None);
    }

    let chrome_ver: Option<&str> = ua
        .split("Chrome/")
        .nth(1)
        .and_then(|s| s.split_whitespace().next());
    let major: Option<&str> = chrome_ver.and_then(|v| v.split('.').next());

    let mut builder = UserAgentMetadata::builder()
        .platform("Android")
        .platform_version("14.0.0")
        .architecture("")
        .model("")
        .mobile(true)
        .bitness("64")
        .wow64(false);

    if let (Some(major), Some(full)) = (major, chrome_ver) {
        builder = builder
            .brands([
                UserAgentBrandVersion::new("Chromium", major),
                UserAgentBrandVersion::new("Google Chrome", major),
                UserAgentBrandVersion::new("Not_A Brand", "24"),
            ])
            .full_version_lists([
                UserAgentBrandVersion::new("Chromium", full),
                UserAgentBrandVersion::new("Google Chrome", full),
                UserAgentBrandVersion::new("Not_A Brand", "24.0.0.0"),
            ]);
    }

    ("Linux armv8l".to_string(), builder.build().ok())
}

impl Page {
    /// Apply stealth settings to this page.
    pub(in crate::internal::browser) async fn apply_stealth(
        &self,
        cfg: &StealthConfig,
    ) -> Result<()> {
        self.pre_navigation_stealth.store(true, Ordering::Relaxed);
        match cfg.navigator_webdriver {
            NavigatorWebdriverPolicy::BrowserReported => {}
        }
        // Probe the browser's real UA and strip only its "Headless" token.
        // Applying the override even when nothing was stripped keeps
        // navigator.platform and Client Hints coupled to the same exact
        // browser product rather than allowing empty or stale metadata.
        let identity = probe_browser_identity(&self.inner).await?;
        let mut builder = SetUserAgentOverrideParams::builder()
            .user_agent(dehead(&identity.user_agent))
            .accept_language(&cfg.locale)
            .platform(identity.platform);
        if let Some(metadata) = identity.metadata {
            builder = builder.user_agent_metadata(metadata);
        }
        let params = builder.build().map_err(VoidCrawlError::PageError)?;
        self.inner
            .execute(params)
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;

        // Viewport / device metrics — through `set_viewport` (not a raw
        // CDP call) so `viewport_override` reflects this as the page's
        // baseline. Otherwise a later one-shot `screenshot(viewport: ...)`
        // would see `current_viewport() == None`, "restore" by calling
        // `clear_viewport`, and wipe this launch-time override instead of
        // putting it back.
        self.set_viewport(Viewport::custom(cfg.viewport_width, cfg.viewport_height))
            .await?;

        Ok(())
    }

    /// Install JavaScript that runs before every subsequent document in this
    /// tab. The script is registered through CDP; it does not modify fetch,
    /// XHR, or request interception.
    pub async fn add_init_script(&self, script: &str) -> Result<()> {
        self.ensure_active().await?;
        self.inner
            .execute(AddScriptToEvaluateOnNewDocumentParams::new(
                script.to_string(),
            ))
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }
}
