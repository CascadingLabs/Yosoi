//! Arm acknowledgement is separate from parked DOM-observer completion.

use super::{
    session::{Page, SessionError},
    transport::BidiConnection,
};
use serde_json::{Value, json};
use std::fmt;
use std::time::Duration;
use tokio::runtime::Handle as RuntimeHandle;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

pub struct ConditionWait {
    connection: BidiConnection,
    realm: String,
    handle: Option<String>,
    deadline: Instant,
}

impl fmt::Debug for ConditionWait {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BidiConditionWait")
            .field("active", &self.handle.is_some())
            .finish_non_exhaustive()
    }
}

impl ConditionWait {
    pub async fn finish(&mut self) -> Result<bool, SessionError> {
        let handle = self.handle.as_ref().ok_or(SessionError::Context)?;
        let token = CancellationToken::new();
        let result = self.connection.command("script.callFunction", json!({"target":{"realm":self.realm},"functionDeclaration":"promise=>promise","arguments":[{"handle":handle}],"awaitPromise":true,"resultOwnership":"none"}), &token, self.deadline).await?;
        if result.get("type").and_then(Value::as_str) != Some("success") {
            return Err(SessionError::Script);
        }
        let value = result
            .get("result")
            .filter(|value| value.get("type").and_then(Value::as_str) == Some("boolean"))
            .and_then(|value| value.get("value"))
            .and_then(Value::as_bool)
            .ok_or(SessionError::Serialization)?;
        self.connection
            .command(
                "script.disown",
                json!({"target":{"realm":self.realm},"handles":[handle]}),
                &token,
                self.deadline,
            )
            .await?;
        self.handle = None;
        Ok(value)
    }
}

impl Drop for ConditionWait {
    fn drop(&mut self) {
        let Some(handle) = self.handle.take() else {
            return;
        };
        let Ok(runtime) = RuntimeHandle::try_current() else {
            self.connection.fence();
            return;
        };
        let connection = self.connection.clone();
        let realm = self.realm.clone();
        runtime.spawn(async move {
            let Some(deadline) = Instant::now().checked_add(Duration::from_secs(2)) else { connection.fence(); return; };
            let token = CancellationToken::new();
            let cleanup = async {
                connection.command("script.callFunction", json!({"target":{"realm":realm},"functionDeclaration":"promise=>{promise.cancel();return true}","arguments":[{"handle":handle}],"awaitPromise":false}), &token, deadline).await?;
                connection.command("script.disown", json!({"target":{"realm":realm},"handles":[handle]}), &token, deadline).await?;
                Ok::<_, super::transport::BidiError>(())
            }.await;
            if cleanup.is_err() { connection.fence(); }
        });
    }
}

impl Page {
    pub async fn start_condition_wait(
        &self,
        expression: &str,
        maximum: Duration,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<ConditionWait, SessionError> {
        let timeout_ms = u64::try_from(maximum.as_millis()).map_err(|_| SessionError::Capacity)?;
        if timeout_ms == 0 || timeout_ms > 2_147_483_647 || expression.len() > 1024 * 1024 {
            return Err(SessionError::Capacity);
        }
        let response_deadline = Instant::now()
            .checked_add(maximum)
            .and_then(|deadline| deadline.checked_add(Duration::from_secs(2)))
            .ok_or(SessionError::Capacity)?;
        let (_, realm) = self.evaluate("0", cancellation, deadline).await?;
        let source = format!(
            r#"(()=>{{
            let stop;
            const promise=new Promise((resolve,reject)=>{{
                let observer,timer,settled=false;
                const events=['load','transitionend','animationend','input','change'];
                const cleanup=()=>{{observer?.disconnect();clearTimeout(timer);for(const event of events)document.removeEventListener(event,check,true);window.removeEventListener('resize',check)}};
                const done=value=>{{if(settled)return;settled=true;cleanup();resolve(value)}};
                const check=()=>{{if(settled)return;try{{if({expression})done(true)}}catch(error){{settled=true;cleanup();reject(error)}}}};
                stop=()=>done(false);
                observer=new MutationObserver(check);
                observer.observe(document,{{childList:true,attributes:true,characterData:true,subtree:true}});
                for(const event of events)document.addEventListener(event,check,true);
                window.addEventListener('resize',check);
                timer=setTimeout(()=>done(false),{timeout_ms});check();
            }});
            promise.cancel=()=>stop();return promise;
        }})()"#
        );
        let reply = self.command("script.evaluate", json!({"expression":source,"target":{"realm":realm},"awaitPromise":false,"resultOwnership":"root"}), cancellation, deadline).await?;
        let handle = reply
            .get("result")
            .and_then(|result| result.get("handle"))
            .and_then(Value::as_str)
            .filter(|handle| !handle.is_empty() && handle.len() <= 512)
            .ok_or(SessionError::Script)?
            .to_owned();
        Ok(ConditionWait {
            connection: self.session.connection.clone(),
            realm,
            handle: Some(handle),
            deadline: response_deadline,
        })
    }
}
