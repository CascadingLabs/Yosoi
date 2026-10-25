//! Trusted native input with owned node handles and fresh hit testing.

use serde_json::{Value, json};
use std::time::Duration;
use tokio::runtime::Handle as RuntimeHandle;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use super::session::{Page, SessionError, moli_realm_alias, remote_json};
use super::transport::{BidiConnection, BidiError, EventStream};
use crate::browser::{BrowserEngine, MoliProfile};

struct Target {
    realm: String,
    handle: String,
    shared_id: Option<String>,
    guard: Option<String>,
    connection: BidiConnection,
    released: bool,
}

impl Drop for Target {
    fn drop(&mut self) {
        if self.released {
            return;
        }
        let Ok(runtime) = RuntimeHandle::try_current() else {
            self.connection.fence();
            return;
        };
        let connection = self.connection.clone();
        let realm = self.realm.clone();
        let handle = self.handle.clone();
        let guard = self.guard.clone();
        runtime.spawn(async move {
            let Some(deadline) = Instant::now().checked_add(Duration::from_secs(2)) else {
                connection.fence();
                return;
            };
            if cleanup_target(
                &connection,
                &realm,
                &handle,
                guard.as_deref(),
                &CancellationToken::new(),
                deadline,
            )
            .await
            .is_err()
            {
                connection.fence();
            }
        });
    }
}

impl Page {
    async fn resolve_input(
        &self,
        selector: &str,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<Target, SessionError> {
        if selector.is_empty() || selector.len() > 16_384 {
            return Err(SessionError::InvalidInput);
        }
        if self.session.config.engine == BrowserEngine::Moli
            && self.session.config.moli_profile != MoliProfile::Layout
        {
            return Err(SessionError::Unsupported(
                "native pointer input requires the Moli layout profile",
            ));
        }
        let (_, realm) = self.evaluate("0", cancellation, deadline).await?;
        let selector = serde_json::to_string(selector).map_err(|_| SessionError::Serialization)?;
        let expression = format!(
            "(()=>{{const nodes=document.querySelectorAll({selector});return nodes.length===1?nodes.item(0):null}})()"
        );
        let reply = self.command("script.evaluate", json!({"expression":expression,"target":{"realm":realm},"awaitPromise":false,"resultOwnership":"root"}), cancellation, deadline).await?;
        let node = reply
            .get("result")
            .filter(|node| node.get("type").and_then(Value::as_str) == Some("node"))
            .ok_or(SessionError::InvalidInput)?;
        let handle = node
            .get("handle")
            .and_then(Value::as_str)
            .filter(|handle| !handle.is_empty() && handle.len() <= 512)
            .ok_or(SessionError::Context)?
            .to_owned();
        let shared_id = node
            .get("sharedId")
            .and_then(Value::as_str)
            .filter(|id| !id.is_empty() && id.len() <= 512)
            .map(str::to_owned);
        let nested_surface = node
            .get("value")
            .and_then(|value| value.get("localName"))
            .and_then(Value::as_str)
            .is_some_and(|tag| {
                ["iframe", "frame", "object", "embed"]
                    .iter()
                    .any(|candidate| tag.eq_ignore_ascii_case(candidate))
            });
        let target = Target {
            realm,
            handle,
            shared_id,
            guard: None,
            connection: self.session.connection.clone(),
            released: false,
        };
        if nested_surface {
            self.release_target(target, cancellation, deadline).await?;
            return Err(SessionError::Unsupported(
                "native input into embedded browsing surfaces",
            ));
        }
        Ok(target)
    }

    async fn target_call(
        &self,
        target: &Target,
        declaration: &str,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<Value, SessionError> {
        let reply = self
            .command(
                "script.callFunction",
                json!({"target":{"realm":target.realm},"functionDeclaration":declaration,
            "arguments":[{"handle":target.handle}],"awaitPromise":true,"resultOwnership":"none",
            "serializationOptions":{"maxObjectDepth":4}}),
                cancellation,
                deadline,
            )
            .await?;
        if reply.get("type").and_then(Value::as_str) != Some("success")
            || reply.get("realm").and_then(Value::as_str) != Some(target.realm.as_str())
        {
            return Err(SessionError::DocumentChanged);
        }
        remote_json(reply.get("result").ok_or(SessionError::Serialization)?, 0)
    }

    async fn release_target(
        &self,
        mut target: Target,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        if let Err(error) = cleanup_target(
            &target.connection,
            &target.realm,
            &target.handle,
            target.guard.as_deref(),
            cancellation,
            deadline,
        )
        .await
        {
            target.connection.fence();
            return Err(error.into());
        }
        target.released = true;
        Ok(())
    }

    async fn arm_input_guard(
        &self,
        target: &mut Target,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<(EventStream, String), SessionError> {
        let events = self.session.connection.subscribe()?;
        let channel = self.session.input_channel().await?;
        let reply = self.command("script.callFunction", json!({
            "target":{"realm":target.realm},"awaitPromise":false,"resultOwnership":"root",
            "serializationOptions":{"maxObjectDepth":0,"maxDomDepth":0},
            "arguments":[{"handle":target.handle},{"type":"channel","value":{"channel":channel}}],
            "functionDeclaration":"(element,notify)=>{if(!element.isConnected || element.ownerDocument!==document)return null;let keys=0;const clicked=event=>{if(event.isTrusted && event.button===0 && (event.target===element||element.contains(event.target))){element.removeEventListener('click',clicked,true);notify('trusted-click')}};const keyed=event=>{if(event.isTrusted)keys++};element.addEventListener('click',clicked,true);element.addEventListener('keydown',keyed,true);return {get keys(){return keys},stop(){element.removeEventListener('click',clicked,true);element.removeEventListener('keydown',keyed,true);return true}}}"
        }), cancellation, deadline).await?;
        let handle = reply
            .get("result")
            .and_then(|result| result.get("handle"))
            .and_then(Value::as_str)
            .filter(|handle| !handle.is_empty() && handle.len() <= 512);
        if reply.get("type").and_then(Value::as_str) != Some("success")
            || reply.get("realm").and_then(Value::as_str) != Some(target.realm.as_str())
            || handle.is_none()
        {
            // The install may have partially registered a listener; an unknown
            // handle cannot be allowed to outlive this logical session.
            self.session.connection.fence();
            return Err(SessionError::DocumentChanged);
        }
        target.guard = handle.map(str::to_owned);
        Ok((events, channel))
    }

    async fn confirm_click(
        &self,
        target: &Target,
        mut events: EventStream,
        channel: &str,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        let confirmation = Instant::now()
            .checked_add(Duration::from_secs(2))
            .ok_or(SessionError::Capacity)?
            .min(deadline);
        loop {
            let event = events.next(cancellation, confirmation).await?;
            if event.method != "script.message"
                || event.params.get("channel").and_then(Value::as_str) != Some(channel)
            {
                continue;
            }
            let source = event
                .params
                .get("source")
                .ok_or(SessionError::DocumentChanged)?;
            let context = source.get("context").and_then(Value::as_str);
            let realm = source
                .get("realm")
                .and_then(Value::as_str)
                .filter(|realm| realm.len() <= 512)
                .ok_or(SessionError::DocumentChanged)?;
            let realm = if self.session.config.engine == BrowserEngine::Moli {
                moli_realm_alias(&self.context, realm)?
            } else {
                realm.to_owned()
            };
            if context != Some(self.context.as_str())
                || realm != target.realm
                || event
                    .params
                    .get("data")
                    .and_then(|data| data.get("type"))
                    .and_then(Value::as_str)
                    != Some("string")
                || event
                    .params
                    .get("data")
                    .and_then(|data| data.get("value"))
                    .and_then(Value::as_str)
                    != Some("trusted-click")
            {
                return Err(SessionError::DocumentChanged);
            }
            return Ok(());
        }
    }

    async fn input_point(
        &self,
        target: &Target,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<Value, SessionError> {
        if self.session.config.engine == BrowserEngine::Moli {
            // Moli's layout is on-demand. A native visual observation refreshes
            // geometry before measuring; DOM-only approximations are not used.
            self.screenshot_png(cancellation, deadline).await?;
        }
        let point = self.target_call(target, "element=>{if(!element.isConnected || element.disabled)return null;const r=element.getBoundingClientRect();const left=Math.max(0,r.left),top=Math.max(0,r.top),right=Math.min(innerWidth,r.right),bottom=Math.min(innerHeight,r.bottom);if(right<=left||bottom<=top)return null;const x=Math.floor((left+right)/2),y=Math.floor((top+bottom)/2);const hit=document.elementFromPoint(x,y);if(!hit||!(hit===element||element.contains(hit)))return null;return {x,y,left:r.left,top:r.top,width:r.width,height:r.height}}", cancellation, deadline).await?;
        if point.is_null() {
            return Err(SessionError::InvalidInput);
        }
        for key in ["x", "y"] {
            let coordinate = point
                .get(key)
                .and_then(Value::as_i64)
                .ok_or(SessionError::Context)?;
            let _ = i32::try_from(coordinate).map_err(|_| SessionError::Context)?;
        }
        Ok(point)
    }

    async fn click_target(
        &self,
        target: &mut Target,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        if self.session.config.engine == BrowserEngine::Moli {
            // Newly changed DOM can leave Moli's scroll extents dirty. Refresh
            // before scrolling, then input_point refreshes the scrolled view.
            self.screenshot_png(cancellation, deadline).await?;
        }
        let scrolled = self.target_call(target, "element=>{if(!element.isConnected)return false;element.scrollIntoView({block:'center',inline:'center',behavior:'instant'});return true}", cancellation, deadline).await?;
        if scrolled != Value::Bool(true) {
            return Err(SessionError::Context);
        }
        let before = self.input_point(target, cancellation, deadline).await?;
        let movement = if self.session.config.engine == BrowserEngine::Moli {
            json!({"type":"pointerMove","origin":"viewport","x":before.get("x"),"y":before.get("y")})
        } else {
            let shared = target.shared_id.as_ref().ok_or(SessionError::Context)?;
            json!({"type":"pointerMove","origin":{"type":"element","element":{"sharedId":shared}},"x":0,"y":0})
        };
        self.command("input.performActions", json!({"context":self.context,"actions":[{"type":"pointer","id":"yosoi-pointer","parameters":{"pointerType":"mouse"},"actions":[movement]}]}), cancellation, deadline).await?;
        let after = self
            .input_point(target, cancellation, deadline)
            .await
            .map_err(|error| match error {
                SessionError::InvalidInput => SessionError::DocumentChanged,
                error => error,
            })?;
        if before != after {
            return Err(SessionError::DocumentChanged);
        }
        if self.ready_realm(cancellation, deadline).await? != target.realm {
            return Err(SessionError::DocumentChanged);
        }
        let (events, channel) = self.arm_input_guard(target, cancellation, deadline).await?;
        self.command("input.performActions", json!({"context":self.context,"actions":[{"type":"pointer","id":"yosoi-pointer","parameters":{"pointerType":"mouse"},"actions":[{"type":"pointerDown","button":0},{"type":"pointerUp","button":0}]}]}), cancellation, deadline).await?;
        self.confirm_click(target, events, &channel, cancellation, deadline)
            .await
    }

    #[expect(
        clippy::significant_drop_tightening,
        reason = "The target is consumed by bounded async release before returning."
    )]
    pub async fn click_unique_element(
        &self,
        selector: &str,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        let mut target = self.resolve_input(selector, cancellation, deadline).await?;
        let result = async {
            self.click_target(&mut target, cancellation, deadline)
                .await?;
            self.ready_realm(cancellation, deadline).await?;
            Ok::<(), SessionError>(())
        }
        .await;
        let cleanup = self.release_target(target, cancellation, deadline).await;
        result?;
        cleanup
    }

    #[expect(
        clippy::significant_drop_tightening,
        reason = "The target is consumed by bounded async release before returning."
    )]
    pub async fn type_into_unique_element(
        &self,
        selector: &str,
        text: &str,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        // This API accepts literal text, not WebDriver key commands. Reserved
        // scalars must not turn a permitted text entry into Enter/Tab/Delete.
        if text.len() > 16_384
            || text.chars().any(|character| {
                character.is_control() || ('\u{e000}'..='\u{e0ff}').contains(&character)
            })
        {
            return Err(SessionError::InvalidInput);
        }
        let mut target = self.resolve_input(selector, cancellation, deadline).await?;
        let result = async {
            self.click_target(&mut target, cancellation, deadline).await?;
            if self.ready_realm(cancellation, deadline).await? != target.realm { return Err(SessionError::InputTargetLost); }
            let focused = self.target_call(&target, "element=>element.isConnected && document.activeElement===element && !element.disabled && !element.readOnly && (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element.isContentEditable)", cancellation, deadline).await?;
            if focused != Value::Bool(true) { return Err(SessionError::InputTargetLost); }
            let mut actions = Vec::new();
            for character in text.chars() {
                let value = character.to_string();
                actions.push(json!({"type":"keyDown","value":value}));
                actions.push(json!({"type":"keyUp","value":value}));
            }
            if !actions.is_empty() {
                self.command("input.performActions", json!({"context":self.context,"actions":[{"type":"key","id":"yosoi-keyboard","actions":actions}]}), cancellation, deadline).await?;
                if self.ready_realm(cancellation, deadline).await? != target.realm { return Err(SessionError::DocumentChanged); }
                let guard = target.guard.as_ref().ok_or(SessionError::DocumentChanged)?;
                let report = self.command("script.callFunction", json!({"target":{"realm":target.realm},"functionDeclaration":"guard=>guard.keys","arguments":[{"handle":guard}],"awaitPromise":false}), cancellation, deadline).await?;
                if report.get("type").and_then(Value::as_str) != Some("success") || report.get("realm").and_then(Value::as_str) != Some(target.realm.as_str()) { return Err(SessionError::DocumentChanged); }
                let count = report.get("result").and_then(|result| result.get("value")).and_then(Value::as_u64);
                if count != u64::try_from(text.chars().count()).ok() { return Err(SessionError::DocumentChanged); }
            }
            Ok(())
        }.await;
        let cleanup = self.release_target(target, cancellation, deadline).await;
        result?;
        cleanup
    }
}

async fn cleanup_target(
    connection: &BidiConnection,
    realm: &str,
    node: &str,
    guard: Option<&str>,
    cancellation: &CancellationToken,
    deadline: Instant,
) -> Result<(), BidiError> {
    let cleanup = async {
        if let Some(guard) = guard {
            let reply = connection.command("script.callFunction", json!({"target":{"realm":realm},"functionDeclaration":"guard=>guard.stop()","arguments":[{"handle":guard}],"awaitPromise":false}), cancellation, deadline).await?;
            if reply.get("type").and_then(Value::as_str) != Some("success") || reply.get("realm").and_then(Value::as_str) != Some(realm) { return Err(BidiError::InvalidMessage); }
        }
        let mut handles = vec![node];
        if let Some(guard) = guard { handles.push(guard); }
        connection.command("script.disown", json!({"target":{"realm":realm},"handles":handles}), cancellation, deadline).await?;
        Ok(())
    }.await;
    match cleanup {
        Err(error) if error.remote_target_is_gone() => Ok(()),
        result => result,
    }
}
