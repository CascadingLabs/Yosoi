//! Retained native Session/Work binding; it never launches a second browser.
use super::network::NetworkCapture;
use crate::{
    automation_record::OperationStatus,
    documents::{
        Document, DocumentEpoch, FileDocument, FileLimits, FileMetadata, ImageDocument,
        file_from_bytes,
    },
    internal::browser::page::SurfaceInput,
    internal::web_capture::{
        CharsetDeclaration, ClassificationBasis, ClassificationExtent, DeclarationDisagreement,
        MediaDeclaration, SourceClassificationOutcome, SourceFormat, SourceMediaType, XmlProfile,
        classify_source_bytes, parse_media_declaration,
    },
    session::{ActionKind, Work},
    surface::{
        DocumentPolicies, DocumentPolicy, NetworkObservationPolicy, NetworkPayloadKind,
        NetworkPayloadRef, NetworkPayloadState, NetworkPayloadValue, NetworkProjectionBasis,
        PixelArtifact, PixelLimits, PixelOrientation, Surface,
        connection::{Operation, Result, Trace},
    },
};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use image::ImageReader;
use serde_json::{Value, json};
use std::{collections::HashMap, io, io::Cursor};

pub(super) struct NativeBrowser {
    work: Option<Work>,
    key: String,
    session_id: String,
    tab_id: String,
    binding_id: String,
    pub documents: DocumentPolicies,
    network_policy: NetworkObservationPolicy,
    network: Option<NetworkCapture>,
    network_payloads: HashMap<String, (NetworkPayloadValue, NetworkPayloadRef)>,
}

impl NativeBrowser {
    pub async fn new(
        work: Work,
        mut documents: DocumentPolicies,
        network_policy: NetworkObservationPolicy,
    ) -> Result<Self> {
        documents.validate()?;
        network_policy.validate()?;
        let limit = work.surface_observation_limit();
        documents.dom.max_bytes = documents.dom.max_bytes.min(limit);
        documents.html.max_bytes = documents.html.max_bytes.min(limit);
        let (session_id, tab_id) = work.surface_identity();
        let binding_id = uuid::Uuid::new_v4().to_string();
        // Validate this provider and authority before returning a binding.
        work.surface_script("location", json!({})).await?;
        Ok(Self {
            key: format!("native-{session_id}-{tab_id}-{binding_id}"),
            session_id,
            tab_id,
            binding_id,
            work: Some(work),
            documents,
            network_policy,
            network: None,
            network_payloads: HashMap::new(),
        })
    }

    fn work(&self) -> Result<&Work> {
        self.work
            .as_ref()
            .ok_or_else(|| io::Error::other("native Surface Work was released").into())
    }

    pub fn key(&self) -> &str {
        &self.key
    }

    pub const fn network_window_limit(&self) -> usize {
        self.network_policy.max_windows
    }

    pub fn capabilities(&self) -> Value {
        json!({"backend":"native_session","sessionId":self.session_id,"tabId":self.tab_id,"bindingId":self.binding_id,
            "ownership":"Surface close releases Work; the retained Session and tab are not explicitly closed",
            "networkObservation":{"provider":"chrome_cdp","supported":true,"subscription":"explicit_opt_in","bodyRetention":self.network_policy.retain_bodies,"active":self.network.is_some()}})
    }

    pub async fn subscribe_network(&mut self, retain_bodies: Option<bool>) -> Result<Value> {
        if self.network.is_some() {
            return Err(io::Error::other("native network subscription is already active").into());
        }
        let mut policy = self.network_policy.clone();
        if let Some(retain_bodies) = retain_bodies {
            policy.retain_bodies = retain_bodies;
        }
        policy.validate()?;
        let work = self.work()?;
        let cancellation = work.surface_session_cancellation();
        let authority_cancellation = work.surface_authority_cancellation();
        let subscription = work
            .surface_start_network_subscription(policy.max_events, policy.max_buffered_events)
            .await?;
        let capture = NetworkCapture::start(
            subscription,
            self.session_id.clone(),
            self.tab_id.clone(),
            policy.clone(),
            cancellation,
            authority_cancellation,
        )?;
        self.network_policy = policy;
        self.network = Some(capture);
        Ok(
            json!({"active":true,"subscription_id":self.network.as_ref().map(|value|value.subscription_id()),
            "provider":"chrome_cdp","body_retention":self.network_policy.retain_bodies,
            "max_events":self.network_policy.max_events,"max_duration_ms":self.network_policy.max_duration_ms}),
        )
    }

    pub async fn cancel_network(&mut self) -> Result<Value> {
        if let Some(mut network) = self.network.take() {
            network.close().await?;
        }
        Ok(json!({"active":false,"cancelled":true}))
    }

    pub async fn wait_network_event(&self, after_sequence: u64, timeout_ms: u64) -> Result<Value> {
        let network = self
            .network
            .as_ref()
            .ok_or_else(|| io::Error::other("native network subscription is not active"))?;
        let sequence = network.wait_for_event(after_sequence, timeout_ms).await?;
        Ok(match sequence {
            Some(sequence) => json!({"state":"event","sequence":sequence}),
            None => json!({"state":"timeout","sequence":after_sequence}),
        })
    }

    async fn capture_network_evidence(
        &mut self,
        epoch: u64,
        policy: DocumentPolicy,
    ) -> Result<(Surface, Document, Value)> {
        let mut snapshot = self
            .network
            .as_mut()
            .ok_or_else(|| {
                io::Error::other("subscribe to native network events before observing them")
            })?
            .snapshot(policy.max_bytes)?;
        if self.network_policy.retain_bodies {
            let max_body_bytes = u64::try_from(self.network_policy.max_body_bytes)
                .map_err(|_| io::Error::other("network body limit is unsupported"))?;
            for candidate in snapshot.body_candidates {
                let payload_id = candidate.payload_id.clone();
                let skip_reason = if !self.work()?.surface_authority_active() {
                    Some("native_work_authority_lost_before_body_read")
                } else {
                    match candidate.provider_reported_body_bytes {
                        None => Some("response_body_size_unknown_before_read"),
                        Some(bytes) if bytes > max_body_bytes => {
                            Some("response_body_exceeds_retention_limit_before_read")
                        }
                        Some(_) => None,
                    }
                };
                let (
                    payload,
                    kind,
                    bytes,
                    base64_encoded,
                    text_utf8_normalized,
                    state,
                    document_id,
                    detected_media_type,
                    projection_basis,
                    reason,
                ) = if let Some(reason) = skip_reason {
                    (
                        None,
                        None,
                        Vec::new(),
                        false,
                        false,
                        NetworkPayloadState::Unavailable,
                        None,
                        None,
                        None,
                        Some(reason.into()),
                    )
                } else {
                    let response = self
                        .work()?
                        .surface_capture_network_body(
                            &candidate.request_id,
                            self.network_policy.max_body_bytes,
                        )
                        .await;
                    match response {
                        Ok(body) => {
                            let bytes = body.bytes().to_vec();
                            let truncated = !body.complete;
                            let text_utf8_normalized = !body.provider_base64_encoded;
                            match self.project_network_body(
                                &payload_id,
                                &candidate,
                                &bytes,
                                body.complete,
                                text_utf8_normalized,
                            ) {
                                Ok((
                                    payload,
                                    kind,
                                    document_id,
                                    detected_media_type,
                                    projection_basis,
                                    reason,
                                )) => (
                                    Some(payload),
                                    Some(kind),
                                    bytes,
                                    body.provider_base64_encoded,
                                    text_utf8_normalized,
                                    if truncated {
                                        NetworkPayloadState::Truncated
                                    } else {
                                        NetworkPayloadState::Retained
                                    },
                                    Some(document_id),
                                    detected_media_type,
                                    Some(projection_basis),
                                    reason,
                                ),
                                Err(_) => (
                                    None,
                                    None,
                                    bytes,
                                    body.provider_base64_encoded,
                                    text_utf8_normalized,
                                    NetworkPayloadState::Unsupported,
                                    None,
                                    None,
                                    None,
                                    Some("existing_document_projection_rejected_response".into()),
                                ),
                            }
                        }
                        Err(_) => (
                            None,
                            None,
                            Vec::new(),
                            false,
                            false,
                            NetworkPayloadState::Unavailable,
                            None,
                            None,
                            None,
                            Some("provider_response_body_unavailable".into()),
                        ),
                    }
                };
                let reference = self
                    .network
                    .as_mut()
                    .ok_or_else(|| io::Error::other("network subscription was canceled"))?
                    .retain_body(
                        &candidate,
                        payload_id,
                        &bytes,
                        base64_encoded,
                        text_utf8_normalized,
                        state,
                        kind,
                        document_id,
                        detected_media_type,
                        projection_basis,
                        reason,
                    )?;
                if matches!(
                    reference.state,
                    NetworkPayloadState::Retained | NetworkPayloadState::Truncated
                ) && let Some(payload) = payload
                {
                    self.network_payloads
                        .insert(reference.id.clone(), (payload, reference.clone()));
                }
                if let Some(existing) = snapshot
                    .window
                    .payloads
                    .iter_mut()
                    .find(|existing| existing.id == reference.id)
                {
                    *existing = reference;
                } else {
                    snapshot.window.payloads.push(reference);
                }
            }
        }
        let window = snapshot.window;
        let window_id = window.window_id.clone();
        let bytes = serde_json::to_vec(&window)?;
        let document = window.to_document(format!("surface-{}-network-{epoch}", self.key))?;
        let index = Surface::with_policy(&document, &self.documents)?;
        let mut snapshot = json!({"session_id":self.session_id,"tab_id":self.tab_id,
            "capture_sequence":epoch,"network_window_id":window_id,"network":window,
            "network_schema":crate::surface::NETWORK_OBSERVATION_SCHEMA,"network_schema_version":1,
            "network_window_bytes":bytes.len()});
        let fields = snapshot
            .as_object_mut()
            .ok_or_else(|| io::Error::other("network snapshot was not an object"))?;
        fields.insert("native_session_id".into(), self.session_id.clone().into());
        fields.insert("native_tab_id".into(), self.tab_id.clone().into());
        Ok((index, document, snapshot))
    }

    fn project_network_body(
        &self,
        payload_id: &str,
        candidate: &super::network::NetworkBodyCandidate,
        bytes: &[u8],
        complete: bool,
        text_utf8_normalized: bool,
    ) -> Result<(
        NetworkPayloadValue,
        NetworkPayloadKind,
        String,
        Option<String>,
        NetworkProjectionBasis,
        Option<String>,
    )> {
        let source_media_type = candidate
            .declared_media_type
            .clone()
            .map_or(SourceMediaType::Absent, SourceMediaType::from_text);
        let extent = if complete {
            ClassificationExtent::Complete
        } else {
            ClassificationExtent::RetainedPrefix
        };
        let classification = classify_source_bytes(&source_media_type, bytes, extent);
        let source_format = match &classification {
            SourceClassificationOutcome::Classified(classified) => Some(classified.format()),
            _ => None,
        };
        let detected_media_type = detected_source_media_type(&classification);
        let (html, json) = match source_format {
            Some(SourceFormat::Html) => (true, false),
            Some(SourceFormat::Json) => (false, true),
            _ => (false, false),
        };
        // Base64 is a CDP transport wrapper, not a source-media classification.
        // Preserve exact valid UTF-8 bytes when no conflicting charset requires
        // character decoding; keep the provider-normalization fact unchanged.
        let utf8_view = text_utf8_normalized
            || (std::str::from_utf8(bytes).is_ok()
                && (json
                    || matches!(
                        parse_media_declaration(&source_media_type),
                        MediaDeclaration::Missing
                            | MediaDeclaration::Parsed {
                                charset: CharsetDeclaration::Missing,
                                ..
                            }
                    )
                    || matches!(
                        parse_media_declaration(&source_media_type),
                        MediaDeclaration::Parsed {
                            charset: CharsetDeclaration::Label { canonical, .. },
                            ..
                        } if canonical.eq_ignore_ascii_case("utf-8")
                    )));
        if (html || json) && utf8_view {
            let document = if html {
                Document::html(payload_id, bytes.to_vec())
            } else {
                Document::json(payload_id, bytes.to_vec())
            };
            if let Ok(document) = document
                && document.parse().is_ok()
            {
                let kind = if html {
                    NetworkPayloadKind::Html
                } else {
                    NetworkPayloadKind::Json
                };
                return Ok((
                    NetworkPayloadValue::Document(document),
                    kind,
                    payload_id.to_owned(),
                    detected_media_type,
                    requests_projection_basis(&classification)
                        .unwrap_or(NetworkProjectionBasis::OpaqueBytes),
                    None,
                ));
            }
        }
        let metadata = FileMetadata::new()
            .with_capture_id(candidate.request_id.clone())?
            .with_session_id(self.session_id.clone())?
            .with_tab_id(self.tab_id.clone())?;
        let metadata = if let Some(media_type) = candidate.declared_media_type.as_ref() {
            metadata.with_declared_media_type(media_type.clone())?
        } else {
            metadata
        };
        let maximum = u64::try_from(self.network_policy.max_body_bytes)
            .map_err(|_| io::Error::other("network body limit is unsupported"))?;
        let file: FileDocument = file_from_bytes(
            payload_id,
            bytes.to_vec(),
            metadata,
            FileLimits::new(maximum)?,
        )?;
        let detected_media_type = file
            .metadata()
            .detected_media_type()
            .map(str::to_owned)
            .or(detected_media_type);
        let projection_basis = if file.metadata().detected_media_type().is_some() {
            NetworkProjectionBasis::TypedFileMagic
        } else {
            NetworkProjectionBasis::OpaqueBytes
        };
        let reason = if (html || json) && !utf8_view {
            Some("text_response_body_not_returned_as_unicode_text".into())
        } else if matches!(source_format, Some(SourceFormat::Xml(_))) {
            Some("existing_requests_xml_projection_not_available_for_network_body".into())
        } else if html || json {
            Some("existing_requests_source_projection_rejected_response".into())
        } else {
            None
        };
        Ok((
            NetworkPayloadValue::File(file),
            NetworkPayloadKind::File,
            payload_id.to_owned(),
            detected_media_type,
            projection_basis,
            reason,
        ))
    }

    pub fn read_network_payload(
        &self,
        requested_reference: &NetworkPayloadRef,
        offset: usize,
        max_bytes: usize,
    ) -> Result<Value> {
        if requested_reference.id.is_empty()
            || requested_reference.id.len() > 1_024
            || !(1..=32_768).contains(&max_bytes)
        {
            return Err(io::Error::other("invalid network payload read bounds").into());
        }
        let (payload, reference) = self
            .network_payloads
            .get(&requested_reference.id)
            .ok_or_else(|| io::Error::other("network payload is unavailable or was evicted"))?;
        if reference != requested_reference {
            return Err(
                io::Error::other("network payload reference does not match this Session").into(),
            );
        }
        let bytes = payload.bytes();
        if offset > bytes.len() {
            return Err(io::Error::other("network payload offset is past its end").into());
        }
        let end = offset
            .checked_add(max_bytes)
            .ok_or_else(|| io::Error::other("network payload offset overflowed"))?
            .min(bytes.len());
        let chunk = bytes
            .get(offset..end)
            .ok_or_else(|| io::Error::other("network payload range is invalid"))?;
        Ok(
            json!({"payload":reference,"total_bytes":bytes.len(),"offset":offset,
            "data_base64":STANDARD.encode(chunk),"next_offset":(end < bytes.len()).then_some(end)}),
        )
    }

    pub fn retained_network_payload(
        &self,
        id: &str,
    ) -> Option<(NetworkPayloadRef, NetworkPayloadValue)> {
        self.network_payloads
            .get(id)
            .map(|(payload, reference)| (reference.clone(), payload.clone()))
    }

    pub fn authorize(&self, operation: &Operation) -> Result<()> {
        let (kind, input) = match operation {
            Operation::Click { .. } => (ActionKind::Click, ""),
            Operation::Fill { text, .. } => (ActionKind::EnterText, text.as_str()),
            Operation::Key { key, .. } => (ActionKind::EnterText, key.as_str()),
            Operation::Scroll { .. } => (ActionKind::Scroll, ""),
            Operation::Navigate { url, .. } => (ActionKind::Navigate, url.as_str()),
            _ => return Err(io::Error::other("not a native Surface action").into()),
        };
        Ok(self.work()?.surface_authorize(kind, input)?)
    }

    pub async fn script(&self, operation: &str, input: Value) -> Result<Value> {
        Ok(self.work()?.surface_script(operation, input).await?)
    }

    pub async fn capture(
        &self,
        epoch: u64,
        trace: &mut Trace,
    ) -> Result<(Surface, Document, Value)> {
        let mut captured = self.script("capture", json!({"epoch":epoch,"limits":self.documents.dom,"html_limits":self.documents.html})).await?;
        let native_epoch = captured
            .get("native_document_epoch")
            .and_then(Value::as_u64)
            .ok_or_else(|| io::Error::other("native document epoch missing"))?;
        // Surface's positive capture sequence and the native browser's document
        // epoch are different clocks. An untouched native about:blank starts at
        // epoch zero; preserve that provenance without inventing a native epoch.
        let wire = captured
            .get("wire")
            .ok_or_else(|| io::Error::other("native capture lacks DOM evidence"))?;
        let wire_bytes = serde_json::to_vec(wire)?;
        let captured_fields = captured
            .as_object_mut()
            .ok_or_else(|| io::Error::other("native capture result is not an object"))?;
        captured_fields.insert("session_id".into(), self.session_id.clone().into());
        captured_fields.insert("tab_id".into(), self.tab_id.clone().into());
        captured_fields.insert("capture_sequence".into(), epoch.into());
        let document = Document::rendered_dom(
            format!("surface-{}-{epoch}", self.key),
            DocumentEpoch::try_from(epoch)?,
            wire_bytes,
        )?;
        let index = Surface::with_limits(&document, self.documents.dom.limits()?)?;
        trace.event("capture", json!({"url":captured.get("url"),"epoch":epoch,
            "capture":index.identity(),"nodes":index.node_count(),"source_bytes":index.source_bytes(),
            "native_session_id":self.session_id,"native_tab_id":self.tab_id,"native_document_epoch":native_epoch,"capture_sequence":epoch}));
        Ok((index, document, captured))
    }

    pub async fn capture_evidence(
        &mut self,
        epoch: u64,
        representation: super::BrowserRepresentation,
    ) -> Result<(Surface, Document, Value)> {
        let policy = representation.policy(&self.documents);
        if representation == super::BrowserRepresentation::Network {
            return self.capture_network_evidence(epoch, policy).await;
        }
        let mut location = self.script("location", json!({})).await?;
        let document = match representation {
            super::BrowserRepresentation::Ax => {
                let captured = self.work()?.surface_ax(policy.max_depth).await?;
                let native_epoch = captured
                    .get("native_document_epoch")
                    .and_then(Value::as_u64)
                    .ok_or_else(|| io::Error::other("native AX epoch missing"))?;
                if location
                    .get("native_document_epoch")
                    .and_then(Value::as_u64)
                    != Some(native_epoch)
                {
                    return Err(io::Error::other(
                        "native document changed during AX capture; observe again",
                    )
                    .into());
                }
                let location_object = location
                    .as_object_mut()
                    .ok_or_else(|| io::Error::other("native location result is not an object"))?;
                location_object.insert("session_id".into(), self.session_id.clone().into());
                location_object.insert("tab_id".into(), self.tab_id.clone().into());
                super::evidence::accessibility_document(
                    format!("surface-{}-ax-{epoch}", self.key),
                    epoch,
                    captured
                        .get("nodes")
                        .ok_or_else(|| io::Error::other("native AX nodes missing"))?,
                    policy,
                )?
            }
            super::BrowserRepresentation::Network => {
                return Err(io::Error::other(
                    "network evidence dispatch did not enter its capture path",
                )
                .into());
            }
            super::BrowserRepresentation::Dom => {
                return Err(io::Error::other("DOM capture uses the retained tab").into());
            }
        };
        let index = Surface::with_limits(&document, policy.limits()?)?;
        Ok((index, document, location))
    }

    pub async fn input(&self, input: SurfaceInput) -> Result<String> {
        let receipt = self.work()?.surface_input(&input).await?;
        if receipt.status != OperationStatus::Observed {
            return Err(io::Error::other(format!(
                "native Surface dispatch {:?}: {:?}",
                receipt.status, receipt.error
            ))
            .into());
        }
        Ok(receipt.id)
    }

    pub async fn navigate(&self, url: &str) -> Result<String> {
        let receipt = self.work()?.navigate(url).await?;
        if receipt.status != OperationStatus::Observed {
            return Err(io::Error::other(format!(
                "native navigation {:?}: {:?}",
                receipt.status, receipt.error
            ))
            .into());
        }
        Ok(receipt.id)
    }

    pub async fn screenshot_artifact(&self) -> Result<PixelArtifact> {
        let receipt = self.work()?.screenshot().await?;
        if receipt.status != OperationStatus::Observed {
            return Err(io::Error::other("native screenshot did not complete").into());
        }
        let bytes = receipt
            .observation
            .and_then(|value| value.screenshot)
            .ok_or_else(|| io::Error::other("native screenshot evidence missing"))?;
        let pixel_limits = PixelLimits::default().validate()?;
        let max_bytes = u64::try_from(pixel_limits.max_output_bytes)
            .map_err(|_| io::Error::other("native screenshot byte limit is unsupported"))?;
        let document = ImageDocument::from_bytes_with_limits(
            format!("surface-screenshot-{}", receipt.id),
            bytes,
            FileLimits::new(max_bytes)?,
        )?;
        let dimensions = ImageReader::new(Cursor::new(document.bytes()))
            .with_guessed_format()?
            .into_dimensions()?;
        PixelArtifact::from_image_document(
            document,
            dimensions.0,
            dimensions.1,
            PixelOrientation::ExifUnapplied,
        )
        .map_err(|error| io::Error::other(error.to_string()).into())
    }

    pub async fn close(&mut self) -> Result<()> {
        if let Some(mut network) = self.network.take() {
            network.close().await?;
        }
        if let Some(work) = self.work.take() {
            work.release().await?;
        }
        Ok(())
    }
}

fn detected_source_media_type(classification: &SourceClassificationOutcome) -> Option<String> {
    let format = match classification {
        SourceClassificationOutcome::Classified(classified)
            if classified.basis() == ClassificationBasis::Sniffed =>
        {
            Some(classified.format())
        }
        SourceClassificationOutcome::Classified(classified) => match classified.disagreement() {
            DeclarationDisagreement::Supports => Some(classified.format()),
            DeclarationDisagreement::Conflicts(format) => Some(format),
            DeclarationDisagreement::Inconclusive => None,
        },
        SourceClassificationOutcome::Unsupported { candidates, .. }
        | SourceClassificationOutcome::Unknown { candidates, .. }
            if candidates.len() == 1 =>
        {
            candidates.first().copied()
        }
        SourceClassificationOutcome::Unknown { .. }
        | SourceClassificationOutcome::Unsupported { .. }
        | SourceClassificationOutcome::Ambiguous { .. } => None,
    }?;
    let media_type = match format {
        SourceFormat::Html => "text/html",
        SourceFormat::Xml(XmlProfile::Xhtml) => "application/xhtml+xml",
        SourceFormat::Xml(XmlProfile::Generic) => "application/xml",
        SourceFormat::Json => "application/json",
        SourceFormat::PlainText => "text/plain",
    };
    Some(media_type.to_owned())
}

fn requests_projection_basis(
    classification: &SourceClassificationOutcome,
) -> Option<NetworkProjectionBasis> {
    let SourceClassificationOutcome::Classified(classified) = classification else {
        return None;
    };
    Some(match classified.basis() {
        ClassificationBasis::Declared => NetworkProjectionBasis::RequestsDeclared,
        ClassificationBasis::StructuredSuffix => NetworkProjectionBasis::RequestsStructuredSuffix,
        ClassificationBasis::Sniffed => NetworkProjectionBasis::RequestsSniffed,
    })
}
