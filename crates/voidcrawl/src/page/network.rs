use super::Page;
use crate::error::Result;
use crate::error::VoidCrawlError;
use chromiumoxide::cdp::browser_protocol::network::Cookie;
use chromiumoxide::cdp::browser_protocol::network::CookieParam;
use chromiumoxide::cdp::browser_protocol::network::DeleteCookiesParams;
use chromiumoxide::cdp::browser_protocol::network::Headers;
use chromiumoxide::cdp::browser_protocol::network::SetExtraHttpHeadersParams;
use std::collections::HashMap;

impl Page {
    // ── Headers & Network ───────────────────────────────────────────────

    /// Set extra HTTP headers for all subsequent requests from this page.
    pub async fn set_headers(&self, headers: HashMap<String, String>) -> Result<()> {
        self.ensure_active().await?;
        self.ensure_network_enabled().await?;
        let json_val =
            serde_json::to_value(&headers).map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let params = SetExtraHttpHeadersParams::new(Headers::new(json_val));
        self.inner
            .execute(params)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    // ── Cookies ─────────────────────────────────────────────────────────

    /// Return all cookies that match the current page URL.
    pub async fn get_cookies(&self) -> Result<Vec<Cookie>> {
        self.inner
            .get_cookies()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))
    }

    /// Set a single cookie on the current page.
    pub async fn set_cookie(&self, cookie: CookieParam) -> Result<()> {
        self.ensure_active().await?;
        self.inner
            .set_cookie(cookie)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    /// Set multiple cookies at once.
    pub async fn set_cookies(&self, cookies: Vec<CookieParam>) -> Result<()> {
        self.ensure_active().await?;
        self.inner
            .set_cookies(cookies)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    /// Delete cookies by name, optionally scoped by domain and path.
    pub async fn delete_cookies(&self, cookies: Vec<DeleteCookiesParams>) -> Result<()> {
        self.ensure_active().await?;
        self.inner
            .delete_cookies(cookies)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }
}
