//! Native scoped environment overrides; unsupported device modes fail before mutation.

use serde_json::json;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use super::session::{Page, SessionError};
use crate::internal::browser::{RenderingPreferences, Viewport};
use crate::internal::types::{ColorScheme, ReducedMotion};

#[derive(Default)]
pub(super) struct ViewportState {
    pub viewport: Option<Viewport>,
    // None means the native default. A viewport without a UA leaves this sticky.
    pub user_agent: Option<String>,
}

struct UserAgentMutation<'a> {
    page: &'a Page,
    armed: bool,
}

impl Drop for UserAgentMutation<'_> {
    fn drop(&mut self) {
        if self.armed {
            self.page.session.connection.fence();
        }
    }
}

impl Page {
    pub async fn set_rendering_preferences(
        &self,
        preferences: RenderingPreferences,
        token: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        let mut features = serde_json::Map::new();
        if let Some(color_scheme) = preferences.color_scheme {
            let value = match color_scheme {
                ColorScheme::Light => "light",
                ColorScheme::Dark => "dark",
                ColorScheme::NoPreference => {
                    return Err(SessionError::Unsupported(
                        "BiDi no-preference color scheme override",
                    ));
                }
            };
            features.insert("prefers-color-scheme".to_owned(), json!(value));
        }
        if let Some(reduced_motion) = preferences.reduced_motion {
            features.insert(
                "prefers-reduced-motion".to_owned(),
                json!(match reduced_motion {
                    ReducedMotion::NoPreference => "no-preference",
                    ReducedMotion::Reduce => "reduce",
                }),
            );
        }
        if !features.is_empty() {
            self.command(
                "emulation.setMediaFeaturesOverride",
                json!({"contexts":[self.context],"features":features}),
                token,
                deadline,
            )
            .await?;
        }
        Ok(())
    }

    pub async fn set_viewport(
        &self,
        viewport: Viewport,
        token: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        validate_viewport(&viewport)?;
        let mut current = self.viewport.lock().await;
        let mut mutation = UserAgentMutation {
            page: self,
            armed: false,
        };
        if let Some(agent) = viewport.user_agent.as_deref() {
            // Two commands form one logical change. Never expose a partially
            // applied identity after cancellation or a failed viewport change.
            self.apply_user_agent(Some(agent), token, deadline).await?;
            mutation.armed = true;
        }
        self.apply_viewport(Some(&viewport), token, deadline)
            .await?;
        if let Some(agent) = viewport.user_agent.as_ref() {
            current.user_agent = Some(agent.clone());
        }
        current.viewport = Some(viewport);
        mutation.armed = false;
        drop(mutation);
        drop(current);
        Ok(())
    }

    pub(super) async fn apply_user_agent(
        &self,
        user_agent: Option<&str>,
        token: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        self.command(
            "emulation.setUserAgentOverride",
            json!({"contexts":[self.context],"userAgent":user_agent}),
            token,
            deadline,
        )
        .await?;
        Ok(())
    }

    pub(super) async fn apply_viewport(
        &self,
        viewport: Option<&Viewport>,
        token: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        let (size, dpr) =
            viewport.map_or((serde_json::Value::Null, serde_json::Value::Null), |v| {
                (
                    json!({"width":v.width,"height":v.height}),
                    json!(v.device_scale_factor),
                )
            });
        self.command(
            "browsingContext.setViewport",
            json!({"context":self.context,"viewport":size,"devicePixelRatio":dpr}),
            token,
            deadline,
        )
        .await?;
        Ok(())
    }

    pub async fn set_locale(
        &self,
        locale: &str,
        token: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        self.command(
            "emulation.setLocaleOverride",
            json!({"contexts":[self.context],"locale":locale}),
            token,
            deadline,
        )
        .await?;
        Ok(())
    }

    pub async fn set_timezone(
        &self,
        timezone: &str,
        token: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        self.command(
            "emulation.setTimezoneOverride",
            json!({"contexts":[self.context],"timezone":timezone}),
            token,
            deadline,
        )
        .await?;
        Ok(())
    }
}

pub(super) fn validate_viewport(viewport: &Viewport) -> Result<(), SessionError> {
    // BiDi viewport size/DPR does not imply CDP mobile or touch emulation.
    // Reject composite requests before applying any part of the override.
    if viewport.mobile || viewport.has_touch {
        return Err(SessionError::Unsupported(
            "BiDi mobile/touch/device identity",
        ));
    }
    if viewport
        .user_agent
        .as_ref()
        .is_some_and(|agent| agent.is_empty() || agent.chars().any(char::is_control))
    {
        return Err(SessionError::InvalidArgument {
            operation: "set_viewport",
            reason: "user agent must be nonempty and contain no control characters",
        });
    }
    if viewport.width == 0
        || viewport.height == 0
        || !viewport.device_scale_factor.is_finite()
        || viewport.device_scale_factor <= 0.0
    {
        return Err(SessionError::InvalidArgument {
            operation: "set_viewport",
            reason: "dimensions and finite device scale factor must be positive",
        });
    }
    Ok(())
}
