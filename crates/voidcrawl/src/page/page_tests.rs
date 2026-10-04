#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    reason = "test harness"
)]
mod download_tests {
    use std::{fs, path::Path, time::Duration};

    use tokio::time::timeout;

    use super::super::downloads::download_fs::{
        completed_download, dir_entries, new_complete_files, watch_download_dir,
    };

    fn touch(dir: &Path, name: &str, bytes: usize) {
        fs::write(dir.join(name), vec![0u8; bytes]).unwrap();
    }

    #[test]
    fn new_complete_files_excludes_before_crdownload_and_empty() {
        let d = tempfile::tempdir().unwrap();
        touch(d.path(), "old.bin", 10);
        let before = dir_entries(d.path());
        touch(d.path(), "new.bin", 10);
        touch(d.path(), "partial.crdownload", 10);
        touch(d.path(), "empty.bin", 0);
        let files = new_complete_files(d.path(), &before);
        assert_eq!(files.len(), 1);
        assert_eq!(files[0].0.file_name().unwrap(), "new.bin");
    }

    #[test]
    fn completed_download_accepts_new_file() {
        let d = tempfile::tempdir().unwrap();
        let before = dir_entries(d.path());
        touch(d.path(), "f.bin", 100);
        assert_eq!(
            completed_download(d.path(), &before, 1_000)
                .unwrap()
                .unwrap()
                .bytes,
            100
        );
    }

    #[test]
    fn completed_download_rejects_and_deletes_oversize() {
        let d = tempfile::tempdir().unwrap();
        let before = dir_entries(d.path());
        touch(d.path(), "big.bin", 50);
        assert!(completed_download(d.path(), &before, 8).is_err());
        assert!(
            !d.path().join("big.bin").exists(),
            "oversize file should be deleted"
        );
    }

    #[test]
    fn completed_download_errors_on_multiple_new_files() {
        let d = tempfile::tempdir().unwrap();
        let before = dir_entries(d.path());
        touch(d.path(), "a.bin", 10);
        touch(d.path(), "b.bin", 10);
        assert!(completed_download(d.path(), &before, 1_000).is_err());
    }

    #[tokio::test]
    async fn watcher_reports_new_file_without_polling() {
        let d = tempfile::tempdir().unwrap();
        let (_watcher, mut events) = watch_download_dir(d.path()).unwrap();
        touch(d.path(), "new.bin", 10);
        let event = timeout(Duration::from_secs(1), events.recv())
            .await
            .expect("watcher event timeout");
        assert!(event.is_some());
    }
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    reason = "test harness"
)]
mod tests {
    use std::collections::HashSet;

    use chromiumoxide::cdp::browser_protocol::browser::BrowserContextId;
    use serde_json::json;

    use super::super::ProviderBrowserContextIdentity;
    use super::super::document::selector_wait_status;
    use super::super::identity::{
        client_hints_for_ua, client_hints_for_ua_with_full_version, dehead,
    };
    use super::super::navigation_response::{finalize_endpoints, safe_endpoint};
    use crate::VoidCrawlError;

    #[test]
    fn provider_browser_context_identity_debug_is_redacted() {
        let identity =
            ProviderBrowserContextIdentity(BrowserContextId::new("raw-provider-context-id"));
        let debug = format!("{identity:?}");
        assert_eq!(debug, "ProviderBrowserContextIdentity(<redacted>)");
        assert!(!debug.contains("raw-provider-context-id"));
    }

    #[test]
    fn selector_wait_status_classifies_typed_timeout_without_provider_text() {
        assert!(selector_wait_status(Some(&json!(true)), "#ready", 10).is_ok());

        match selector_wait_status(Some(&json!(false)), "#missing", 10) {
            Err(VoidCrawlError::Timeout(message)) => assert!(message.contains("#missing")),
            other => panic!("expected Timeout, got {other:?}"),
        }

        match selector_wait_status(Some(&json!("unexpected")), "#bad", 10) {
            Err(VoidCrawlError::JsEvalError(message)) => {
                assert_eq!(message, "wait_for_selector returned a non-boolean status");
            }
            other => panic!("expected JsEvalError, got {other:?}"),
        }
    }

    #[test]
    fn safe_endpoint_strips_query_and_fragment() {
        assert_eq!(
            safe_endpoint("https://api.example.com/v2/search?token=SECRET&q=ada#frag"),
            Some("https://api.example.com/v2/search".to_string())
        );
        // host + scheme lowercased; bare host, no path.
        assert_eq!(
            safe_endpoint("HTTPS://API.Example.COM"),
            Some("https://api.example.com".to_string())
        );
        // non-default port is kept (it's infra signature, not a secret).
        assert_eq!(
            safe_endpoint("https://api.example.com:8443/v1/quote"),
            Some("https://api.example.com:8443/v1/quote".to_string())
        );
    }

    #[test]
    fn safe_endpoint_drops_userinfo_and_nonhttp_and_local() {
        // userinfo (embedded credentials) removed.
        assert_eq!(
            safe_endpoint("https://alice:hunter2@host.com/p"),
            Some("https://host.com/p".to_string())
        );
        // non-http(s) schemes are never archived.
        assert_eq!(safe_endpoint("ws://host.com/socket"), None);
        assert_eq!(safe_endpoint("data:text/html,hi"), None);
        // loopback / private / link-local hosts (operator environment) dropped.
        assert_eq!(safe_endpoint("http://127.0.0.1:9000/api"), None);
        assert_eq!(safe_endpoint("http://localhost/api"), None);
        assert_eq!(safe_endpoint("http://192.168.1.5/api"), None);
        assert_eq!(safe_endpoint("http://172.16.0.9/api"), None);
        // 172.x outside the private 16-31 band is public — kept.
        assert!(safe_endpoint("http://172.32.0.1/api").is_some());
    }

    #[test]
    fn safe_endpoint_redacts_secret_path_segments() {
        // JWT-like high-entropy blob.
        let jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9";
        assert_eq!(
            safe_endpoint(&format!("https://h.com/reset/{jwt}")),
            Some("https://h.com/reset/:redacted".to_string())
        );
        // email PII segment.
        assert_eq!(
            safe_endpoint("https://h.com/u/ada@example.com/profile"),
            Some("https://h.com/u/:redacted/profile".to_string())
        );
        // long digit run (card/SSN/phone range).
        assert_eq!(
            safe_endpoint("https://h.com/pay/4111111111111111"),
            Some("https://h.com/pay/:redacted".to_string())
        );
        // an ordinary short numeric id is NOT redacted — templatizing is the
        // consumer's job, not the crawler's.
        assert_eq!(
            safe_endpoint("https://h.com/users/123/profile"),
            Some("https://h.com/users/123/profile".to_string())
        );
    }

    #[test]
    fn safe_endpoint_redacts_by_default_holes() {
        // Holes a denylist missed; redact-by-default catches them:
        // a >15-char opaque token (a real key would be kept under the old >=32
        // rule; a low-entropy stand-in here keeps the secret-scanner happy).
        assert_eq!(
            safe_endpoint("https://h.com/v1/keys/tokentokentokentoken"),
            Some("https://h.com/v1/keys/:redacted".to_string())
        );
        // a 16-char all-hex token (2-class, slipped the old digit+alpha gate).
        assert_eq!(
            safe_endpoint("https://h.com/t/a1b2c3d4e5f6a7b8"),
            Some("https://h.com/t/:redacted".to_string())
        );
        // matrix-param session id (`;jsessionid=`) — never handled before.
        assert_eq!(
            safe_endpoint("https://h.com/store;jsessionid=ABC123/cart"),
            Some("https://h.com/:redacted/cart".to_string())
        );
        // a 12-15 char mixed-case+digit token (under the length/digit/hex caps)
        // is still an opaque secret → redacted by the 3-character-class rule.
        assert_eq!(
            safe_endpoint("https://h.com/s/aB3xK9mP2qR5w"),
            Some("https://h.com/s/:redacted".to_string())
        );
        // template words + a version segment survive (the endpoint skeleton);
        // path case is preserved (only the host is lowercased).
        assert_eq!(
            safe_endpoint("https://q1.finance.yahoo.com/v10/finance/quoteSummary/AAPL"),
            Some("https://q1.finance.yahoo.com/v10/finance/quoteSummary/AAPL".to_string())
        );
    }

    #[test]
    fn safe_endpoint_handles_ipv6_and_cgnat_local_hosts() {
        // bracketed IPv6 loopback — `split(':')` would yield "[" and leak it.
        assert_eq!(safe_endpoint("http://[::1]:9000/api"), None);
        assert_eq!(safe_endpoint("http://[fe80::1]/api"), None);
        // CGNAT (RFC-6598) and mDNS .local are operator-network, not the page.
        assert_eq!(safe_endpoint("http://100.64.0.7/api"), None);
        assert_eq!(safe_endpoint("http://printer.local/status"), None);
        // a public IPv6 host is kept (bracket form parsed correctly).
        assert!(safe_endpoint("http://[2606:4700::1111]/cdn-cgi").is_some());
    }

    #[test]
    fn finalize_endpoints_none_when_not_capturing_else_sorted() {
        let mut seen = HashSet::new();
        seen.insert("https://b.com/2".to_string());
        seen.insert("https://a.com/1".to_string());
        assert_eq!(finalize_endpoints(&seen, false), None);
        assert_eq!(
            finalize_endpoints(&seen, true),
            Some(vec![
                "https://a.com/1".to_string(),
                "https://b.com/2".to_string()
            ])
        );
        // capturing with nothing seen → Some(empty), distinct from None ("not
        // captured").
        assert_eq!(finalize_endpoints(&HashSet::new(), true), Some(vec![]));
    }

    const LINUX_UA: &str = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36";
    const WIN_UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36";
    const MAC_UA: &str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36";

    #[test]
    fn dehead_strips_headless_token() {
        assert_eq!(
            dehead("Mozilla/5.0 HeadlessChrome/148.0.0.0 Safari"),
            "Mozilla/5.0 Chrome/148.0.0.0 Safari"
        );
        // No Headless token → unchanged.
        assert_eq!(dehead(LINUX_UA), LINUX_UA);
    }

    /// navigator.platform + Sec-CH-UA-Platform must match the UA's OS — the
    /// mismatch (Linux UA + "Win32") was the bug.
    #[test]
    fn platform_matches_ua_os() {
        assert_eq!(client_hints_for_ua(LINUX_UA).0, "Linux x86_64");
        assert_eq!(client_hints_for_ua(WIN_UA).0, "Win32");
        assert_eq!(client_hints_for_ua(MAC_UA).0, "MacIntel");

        let md = client_hints_for_ua(LINUX_UA).1.unwrap();
        assert_eq!(md.platform, "Linux");
        assert!(!md.mobile);
        assert_eq!(md.architecture, "x86");
    }

    /// Client-Hints brands are populated and carry the UA's Chrome major
    /// version (empty brands was the other half of the bug).
    #[test]
    fn brands_carry_chrome_major_version() {
        let md = client_hints_for_ua(LINUX_UA).1.unwrap();
        let brands = md.brands.unwrap();
        assert!(
            brands
                .iter()
                .any(|b| b.brand == "Google Chrome" && b.version == "148")
        );
        assert!(
            brands
                .iter()
                .any(|b| b.brand == "Chromium" && b.version == "148")
        );
        // A GREASE entry is present (3 brands total).
        assert_eq!(brands.len(), 3);
        // fullVersionList carries the full version.
        let full = md.full_version_list.unwrap();
        assert!(
            full.iter()
                .any(|b| b.brand == "Google Chrome" && b.version == "148.0.0.0")
        );
    }

    #[test]
    fn browser_product_supplies_exact_full_client_hint_version() {
        let metadata = client_hints_for_ua_with_full_version(LINUX_UA, Some("153.0.8010.36"))
            .1
            .unwrap();
        let full = metadata.full_version_list.unwrap();
        assert!(
            full.iter().any(|brand| {
                brand.brand == "Google Chrome" && brand.version == "153.0.8010.36"
            })
        );
    }

    /// A non-Chrome UA yields no brands rather than a wrong/fabricated one,
    /// but still gets a coherent platform.
    #[test]
    fn non_chrome_ua_has_no_brands() {
        let firefox = "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0";
        let (nav_platform, md) = client_hints_for_ua(firefox);
        assert_eq!(nav_platform, "Linux x86_64");
        assert!(md.unwrap().brands.is_none());
    }
}
