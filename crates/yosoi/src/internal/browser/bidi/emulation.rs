//! Native scoped environment overrides; unsupported device modes fail before mutation.

use serde_json::json;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use super::session::{Page, SessionError};
use crate::internal::browser::{RenderingPreferences, Viewport};
use crate::internal::types::{ColorScheme, ReducedMotion};

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
        // BiDi viewport size/DPR does not imply CDP mobile or touch emulation.
        // Reject composite requests before applying any part of the override.
        if viewport.mobile || viewport.has_touch || viewport.user_agent.is_some() {
            return Err(SessionError::Unsupported(
                "BiDi mobile/touch/device identity",
            ));
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
        self.command(
            "browsingContext.setViewport",
            json!({
                "context":self.context,
                "viewport":{"width":viewport.width,"height":viewport.height},
                "devicePixelRatio":viewport.device_scale_factor,
            }),
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
