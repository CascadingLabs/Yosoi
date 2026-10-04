use super::EXECUTION_CONTEXT_WAIT;
use super::FRAME_NAVIGATION_WAIT;
use super::Page;
use super::shared::event_listener_config;
use super::validation::event_overflow;
use crate::error::Result;
use crate::error::VoidCrawlError;
use chromiumoxide::cdp::browser_protocol::page::EventFrameNavigated;
use chromiumoxide::cdp::browser_protocol::page::EventNavigatedWithinDocument;
use chromiumoxide::cdp::browser_protocol::page::FrameId;
use chromiumoxide::cdp::browser_protocol::page::NavigateParams as PageNavigateParams;
use chromiumoxide::cdp::browser_protocol::target::SessionId;
use chromiumoxide::cdp::js_protocol::runtime::EvaluateParams;
use chromiumoxide::cdp::js_protocol::runtime::EventExecutionContextCreated;
use chromiumoxide::cdp::js_protocol::runtime::ExecutionContextId;
use chromiumoxide::error::CdpError as ChromiumoxideError;
use chromiumoxide::listeners::EventDelivery;
use chromiumoxide::listeners::EventOverflowPolicy;
use futures::StreamExt;
use serde_json::Value;
use tokio::time;

impl Page {
    pub(super) async fn frame_execution_context_with_runtime(
        &self,
        frame_id: FrameId,
        frame_url_pattern: &str,
    ) -> Result<(Option<ExecutionContextId>, SessionId)> {
        self.ensure_runtime_enabled().await?;
        let owning_session = self
            .inner
            .frame_session(frame_id.clone())
            .await
            .map_err(|error| VoidCrawlError::JsEvalError(error.to_string()))?
            .ok_or_else(|| VoidCrawlError::FrameNotFound(frame_url_pattern.to_owned()))?;
        let can_use_default_context = self
            .inner
            .frame_is_session_root(frame_id.clone())
            .await
            .map_err(|error| VoidCrawlError::JsEvalError(error.to_string()))?
            .unwrap_or(false);
        let mut created = self
            .inner
            .event_listener::<EventExecutionContextCreated>(event_listener_config(
                16,
                EventOverflowPolicy::Close,
            ))
            .await
            .map_err(|error| VoidCrawlError::JsEvalError(error.to_string()))?;
        time::timeout(EXECUTION_CONTEXT_WAIT, async {
            loop {
                if let Some(context_id) = self
                    .inner
                    .frame_execution_context_with_session(frame_id.clone())
                    .await
                    .map_err(|error| VoidCrawlError::JsEvalError(error.to_string()))?
                {
                    return Ok((Some(context_id.0), context_id.1));
                }
                if &owning_session != self.inner.session_id() && can_use_default_context {
                    return Ok((None, owning_session));
                }
                match created.next().await {
                    Some(EventDelivery::Event(_)) => {}
                    Some(EventDelivery::Lagged { .. }) => {
                        return Err(event_overflow("frame_execution_context"));
                    }
                    None => return Err(VoidCrawlError::BrowserClosed),
                }
            }
        })
        .await
        .map_err(|_| {
            VoidCrawlError::FrameNotFound(format!(
                "{frame_url_pattern:?}: matched frame has no scriptable execution context \
                 (sandboxed without allow-scripts, cross-process, or detached)"
            ))
        })?
    }

    /// Evaluate a JS expression **inside a specific frame's** execution
    /// context and return the result as a JSON value.
    ///
    /// Unlike [`Page::evaluate_js`] — which always runs in the top document —
    /// this targets the frame whose current URL contains `frame_url_pattern`.
    /// It is the only way to read or drive a **cross-origin** iframe: that
    /// frame's `contentDocument` is `null` from the parent under the
    /// same-origin policy, but CDP can evaluate in the frame's own execution
    /// context, where the origin check is satisfied. `expression` runs as if
    /// it were the frame's own page script (`document` is the frame's
    /// document).
    ///
    /// The match must be unique: more than one frame containing
    /// `frame_url_pattern` returns [`VoidCrawlError::AmbiguousFrame`]; no match
    /// (or a matched frame with no scriptable execution context — e.g. a
    /// `sandbox`ed frame without `allow-scripts`, or one not yet loaded)
    /// returns [`VoidCrawlError::FrameNotFound`].
    ///
    /// Normal CDP mode routes the command through the flat session that owns
    /// the matched frame, including site-isolated OOPIF targets. Minimal mode
    /// deliberately disables child-target auto-attach and reports a missing
    /// scriptable context as [`VoidCrawlError::FrameNotFound`].
    pub async fn evaluate_js_in_frame(
        &self,
        frame_url_pattern: &str,
        expression: &str,
    ) -> Result<Value> {
        self.ensure_active().await?;
        let frame_id = self.resolve_frame(frame_url_pattern).await?;
        let (context_id, session_id) = self
            .frame_execution_context_with_runtime(frame_id.clone(), frame_url_pattern)
            .await?;
        let mut params = EvaluateParams::builder()
            .expression(expression)
            .return_by_value(true)
            .await_promise(true);
        if let Some(context_id) = context_id {
            params = params.context_id(context_id);
        }
        let params = params.build().map_err(VoidCrawlError::JsEvalError)?;
        // `evaluate_expression` (not `evaluate`) so chromiumoxide does not
        // overwrite our explicit `context_id` with the top-document context.
        let result = self
            .inner
            .evaluate_expression_in_frame(frame_id, session_id, params)
            .await
            .map_err(|e| VoidCrawlError::JsEvalError(e.to_string()))?;
        Ok(result.value().cloned().unwrap_or(Value::Null))
    }

    /// Navigate a uniquely matched frame through the flat CDP session that
    /// currently owns it. A concurrent process swap fails closed instead of
    /// sending the navigation through a stale or replacement session.
    pub async fn navigate_frame(&self, frame_url_pattern: &str, url: &str) -> Result<String> {
        self.ensure_active().await?;
        let frame_id = self.resolve_frame(frame_url_pattern).await?;
        let mut navigated = self
            .inner
            .event_listener::<EventFrameNavigated>(event_listener_config(
                16,
                EventOverflowPolicy::Close,
            ))
            .await
            .map_err(|error| VoidCrawlError::NavigationFailed(error.to_string()))?;
        let mut same_document = self
            .inner
            .event_listener::<EventNavigatedWithinDocument>(event_listener_config(
                16,
                EventOverflowPolicy::Close,
            ))
            .await
            .map_err(|error| VoidCrawlError::NavigationFailed(error.to_string()))?;
        let session_id = self
            .inner
            .frame_session(frame_id.clone())
            .await
            .map_err(|error| VoidCrawlError::NavigationFailed(error.to_string()))?
            .ok_or_else(|| VoidCrawlError::FrameNotFound(frame_url_pattern.to_owned()))?;
        let mut params = PageNavigateParams::new(url);
        params.frame_id = Some(frame_id.clone());
        match self
            .inner
            .execute_in_frame_session_raw(frame_id.clone(), session_id, params)
            .await
        {
            Ok(_) | Err(ChromiumoxideError::SessionDetached) => {}
            Err(error) => return Err(VoidCrawlError::NavigationFailed(error.to_string())),
        }
        time::timeout(FRAME_NAVIGATION_WAIT, async {
            loop {
                tokio::select! {
                    delivery = navigated.next() => match delivery {
                        Some(EventDelivery::Event(event)) if event.frame.id == frame_id => {
                            return Ok(event.frame.url.clone());
                        }
                        Some(EventDelivery::Event(_)) => {}
                        Some(EventDelivery::Lagged { .. }) => {
                            return Err(event_overflow("frame_navigation"));
                        }
                        None => return Err(VoidCrawlError::BrowserClosed),
                    },
                    delivery = same_document.next() => match delivery {
                        Some(EventDelivery::Event(event)) if event.frame_id == frame_id => {
                            return Ok(event.url.clone());
                        }
                        Some(EventDelivery::Event(_)) => {}
                        Some(EventDelivery::Lagged { .. }) => {
                            return Err(event_overflow("frame_navigation_same_document"));
                        }
                        None => return Err(VoidCrawlError::BrowserClosed),
                    },
                }
            }
        })
        .await
        .map_err(|_| VoidCrawlError::NavigationTimeout {
            url: url.to_owned(),
            wait_phase: "frame_navigated".to_owned(),
            timeout_secs: FRAME_NAVIGATION_WAIT.as_secs_f64(),
            elapsed_secs: FRAME_NAVIGATION_WAIT.as_secs_f64(),
        })?
    }

    /// Resolve the single frame whose URL contains `pattern`.
    ///
    /// chromiumoxide's handler already tracks the frame tree and each frame's
    /// execution context, so this is a cheap lookup with no extra CDP round
    /// trips beyond reading cached frame URLs.
    ///
    /// **Fails closed on ambiguity.** The match must be *unique*: if more than
    /// one frame's URL contains `pattern`, this returns
    /// [`VoidCrawlError::AmbiguousFrame`] rather than silently picking one.
    /// Frame enumeration order is not stable, and a hostile page can embed a
    /// decoy frame whose URL contains a common substring — so guessing would
    /// risk running the caller's JS in the wrong (possibly attacker-scripted)
    /// frame. Use a specific pattern (e.g. `recaptcha/api2/bframe`, not
    /// `recaptcha`); [`Page::frame_urls`] helps you find one.
    pub(super) async fn resolve_frame(&self, pattern: &str) -> Result<FrameId> {
        let frames = self
            .inner
            .frames()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let mut matched: Vec<(FrameId, String)> = Vec::new();
        for frame_id in frames {
            let url = self
                .inner
                .frame_url(frame_id.clone())
                .await
                .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
            if let Some(url) = url
                && url.contains(pattern)
            {
                matched.push((frame_id, url));
            }
        }
        match matched.len() {
            0 => Err(VoidCrawlError::FrameNotFound(pattern.to_string())),
            1 => Ok(matched.swap_remove(0).0),
            n => {
                let urls = matched
                    .iter()
                    .map(|(_, u)| u.as_str())
                    .collect::<Vec<_>>()
                    .join(", ");
                Err(VoidCrawlError::AmbiguousFrame(format!(
                    "{pattern:?} matched {n} frames ({urls}); use a more specific substring"
                )))
            }
        }
    }

    /// List the URLs of every frame currently tracked on this page, in no
    /// particular order. Useful for discovering the right `frame_url_pattern`
    /// to pass to [`Page::evaluate_js_in_frame`].
    pub async fn frame_urls(&self) -> Result<Vec<String>> {
        let frames = self
            .inner
            .frames()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let mut urls = Vec::with_capacity(frames.len());
        for frame_id in frames {
            if let Some(url) = self
                .inner
                .frame_url(frame_id)
                .await
                .map_err(|e| VoidCrawlError::PageError(e.to_string()))?
            {
                urls.push(url);
            }
        }
        Ok(urls)
    }
}
