//! Web evidence adapter over the existing immutable document index.
use crate::surface::{
    Budget, Continuation, DocumentPolicy, Reference as NativeReference, Surface, SurfaceError,
    model::{
        self, Access, AddressToken, Capability, ContinuationToken, Descriptor, Observation,
        ObservationId, ReadOperation, ReadRequest, ReadResult, SourceId, SurfaceId, SurfaceRead,
    },
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

/// An immutable web view implementing the same reading protocol as a video timeline.
#[derive(Clone, Debug)]
pub struct WebSurface {
    index: Surface,
    descriptor: Descriptor,
    observation: Observation,
    root: model::Reference,
    policy: DocumentPolicy,
}
impl WebSurface {
    /// Wraps captured HTML or a rendered DOM; source identity belongs to the caller's session.
    pub fn new(index: Surface, source: SourceId) -> Result<Self, SurfaceError> {
        Self::with_policy(index, source, DocumentPolicy::default())
    }
    /// Wraps HTML, DOM, native AX, or a browser network-event document with
    /// independently configured response limits. Evidence grants no action authority.
    pub fn with_policy(
        index: Surface,
        source: SourceId,
        mut policy: DocumentPolicy,
    ) -> Result<Self, SurfaceError> {
        policy.validate()?;
        policy.response_bytes = index
            .response_budget(Budget {
                bytes: policy.response_bytes,
                items: 1,
            })
            .bytes;
        let ax = index.representation().contains("accessibility-tree");
        let network = index
            .data
            .json
            .as_ref()
            .and_then(|v| v.get("schema"))
            .and_then(serde_json::Value::as_str)
            == Some("yosoi.network.v1");
        if !index.representation().contains("html")
            && !index.representation().contains("rendered-dom")
            && !ax
            && !network
        {
            return Err(SurfaceError::Invalid(
                "web surface requires HTML, DOM, AX, or browser network evidence".into(),
            ));
        }
        let id = SurfaceId::new(format!("{}:document", source.as_str()))?;
        let mut capabilities = Vec::new();
        for name in ["overview", "inspect", "expand", "search", "parent"] {
            capabilities.push(Capability {
                id: format!("web.{name}@1"),
                access: Access::Read,
                control_domain: None,
                input_schema: format!("yosoi.surface.read.{name}.v1"),
            });
        }
        // The reader advertises no live effects: its owner can add those to its live descriptor.
        let descriptor = Descriptor {
            id: id.clone(),
            source,
            representation: if ax {
                "yosoi.web.ax.v1"
            } else if network {
                "yosoi.web.network.v1"
            } else {
                "yosoi.web.document.v1"
            }
            .into(),
            controllable: false,
            capabilities,
        };
        let mut digest = Sha256::new();
        digest.update(b"yosoi-web-view-v1");
        digest.update(index.identity().as_bytes());
        digest.update(descriptor.source.as_str().as_bytes());
        let observation = Observation {
            id: ObservationId::new(format!("web-v1:{:x}", digest.finalize()))?,
            surface: id,
            coverage: if network {
                super::super::Coverage {
                    complete: false,
                    reason: Some(
                        "browser_network_log_window; completeness is unestablished".into(),
                    ),
                }
            } else {
                index.coverage().clone()
            },
        };
        let root = model::Reference {
            observation: observation.id.clone(),
            address: AddressToken::new(format!("n:{}", index.root().node))?,
        };
        Ok(Self {
            index,
            descriptor,
            observation,
            root,
            policy,
        })
    }
    /// Converts an index reference into a representation-neutral evidence address.
    pub fn reference(&self, reference: &NativeReference) -> Result<model::Reference, SurfaceError> {
        self.index.validate(reference)?;
        Ok(model::Reference {
            observation: self.observation.id.clone(),
            address: AddressToken::new(format!("n:{}", reference.node))?,
        })
    }
    /// Resolves a producer-issued address; this operation still grants no live browser authority.
    pub fn native_reference(
        &self,
        reference: &model::Reference,
    ) -> Result<NativeReference, SurfaceError> {
        if reference.observation != self.observation.id {
            return Err(SurfaceError::WrongCapture);
        }
        let value = reference
            .address
            .as_str()
            .strip_prefix("n:")
            .ok_or_else(|| SurfaceError::Invalid("not a web address".into()))?;
        let node = value
            .parse::<usize>()
            .map_err(|_| SurfaceError::Invalid("invalid web address".into()))?;
        if node.to_string() != value {
            return Err(SurfaceError::Invalid("noncanonical web address".into()));
        }
        let native = NativeReference {
            capture: self.index.identity().into(),
            node,
        };
        self.index.validate(&native)?;
        Ok(native)
    }
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Cursor {
    observation: ObservationId,
    native: Continuation,
}
fn encode(
    token: Continuation,
    observation: &ObservationId,
) -> Result<ContinuationToken, SurfaceError> {
    ContinuationToken::new(
        serde_json::to_string(&Cursor {
            observation: observation.clone(),
            native: token,
        })
        .map_err(|e| SurfaceError::Parse(e.to_string()))?,
    )
}
fn decode(
    token: &ContinuationToken,
    observation: &ObservationId,
) -> Result<Continuation, SurfaceError> {
    let cursor: Cursor =
        serde_json::from_str(token.as_str()).map_err(|e| SurfaceError::Parse(e.to_string()))?;
    if &cursor.observation != observation {
        return Err(SurfaceError::WrongCapture);
    }
    Ok(cursor.native)
}
impl SurfaceRead for WebSurface {
    fn descriptor(&self) -> &Descriptor {
        &self.descriptor
    }
    fn observation(&self) -> &Observation {
        &self.observation
    }
    fn root_reference(&self) -> model::Reference {
        self.root.clone()
    }
    fn read(&self, request: &ReadRequest) -> Result<ReadResult, SurfaceError> {
        let mut bounded = request.clone();
        bounded.budget = self.policy.budget(request.budget);
        let request = &bounded;
        if request.budget.bytes < 512 || request.budget.bytes > 65536 {
            return Err(SurfaceError::Invalid(
                "read budget must be 512..65536 bytes".into(),
            ));
        }
        let token = request
            .continuation
            .as_ref()
            .map(|token| decode(token, &self.observation.id))
            .transpose()?;
        if matches!(request.operation, ReadOperation::Parent { .. })
            && request.continuation.is_some()
        {
            return Err(SurfaceError::Invalid(
                "parent does not accept a continuation".into(),
            ));
        }
        let mut items = request.budget.items.clamp(1, 100);
        loop {
            let budget = Budget {
                bytes: request.budget.bytes.saturating_sub(256),
                items,
            };
            let result = match &request.operation {
                ReadOperation::Parent { reference } => ReadResult::Parent(
                    self.index
                        .parent(&self.native_reference(reference)?)?
                        .map(|r| self.reference(&r))
                        .transpose()?,
                ),
                ReadOperation::Inspect { reference } => {
                    let detail = self.index.inspect(
                        &self.native_reference(reference)?,
                        token.as_ref(),
                        budget,
                    )?;
                    ReadResult::Inspection(model::Inspection {
                        reference: reference.clone(),
                        media_type: detail.media_type,
                        total_bytes: detail.total_bytes,
                        offset: detail.offset,
                        content: detail.content,
                        next: detail
                            .next
                            .map(|token| encode(token, &self.observation.id))
                            .transpose()?,
                        coverage: self.observation.coverage.clone(),
                    })
                }
                operation => {
                    let page = match operation {
                        ReadOperation::Overview => self.index.overview(token.as_ref(), budget)?,
                        ReadOperation::Expand { reference } => self.index.expand(
                            &self.native_reference(reference)?,
                            token.as_ref(),
                            budget,
                        )?,
                        ReadOperation::Search { query } => {
                            self.index.find(query, token.as_ref(), budget)?
                        }
                        _ => return Err(SurfaceError::Invalid("unsupported read".into())),
                    };
                    let entries = page
                        .entries
                        .into_iter()
                        .map(|e| {
                            Ok(model::Entry {
                                reference: self.reference(&e.reference)?,
                                kind: e.kind,
                                label: e.label,
                                preview: e.preview,
                                members: e.members,
                            })
                        })
                        .collect::<Result<Vec<_>, SurfaceError>>()?;
                    ReadResult::Page(model::Page {
                        observation: self.observation.id.clone(),
                        total: page.total,
                        offset: page.offset,
                        entries,
                        next: page
                            .next
                            .map(|token| encode(token, &self.observation.id))
                            .transpose()?,
                        coverage: self.observation.coverage.clone(),
                    })
                }
            };
            if serde_json::to_vec(&result)
                .map_err(|e| SurfaceError::Parse(e.to_string()))?
                .len()
                <= request.budget.bytes
            {
                return Ok(result);
            }
            if items <= 1 {
                return Err(SurfaceError::BudgetTooSmall);
            }
            items = items.saturating_sub(1);
        }
    }
}
