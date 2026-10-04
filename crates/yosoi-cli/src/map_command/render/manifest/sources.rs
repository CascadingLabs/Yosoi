use serde::{
    Serialize, Serializer,
    ser::{SerializeSeq, SerializeStruct},
};
use yosoi_engine::map;

use super::super::wire::{
    StatusView, discovery_source_label, pending_reason_label, reason_label, rejection_label,
    support_document_label,
};

pub(super) struct SourcesView<'a>(pub(super) &'a [map::SourceOutcome]);

impl Serialize for SourcesView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut sequence = serializer.serialize_seq(Some(self.0.len()))?;
        for source in self.0 {
            sequence.serialize_element(&SourceView(source))?;
        }
        sequence.end()
    }
}

struct SourceView<'a>(&'a map::SourceOutcome);

impl Serialize for SourceView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("Source", 3)?;
        state.serialize_field("source", discovery_source_label(self.0.source))?;
        state.serialize_field(
            "source_url",
            &self.0.source_url.as_ref().map(AsRef::<str>::as_ref),
        )?;
        state.serialize_field("status", &SourceStatusView(&self.0.status))?;
        state.end()
    }
}

struct SourceStatusView<'a>(&'a map::SourceStatus);

impl Serialize for SourceStatusView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        match self.0 {
            map::SourceStatus::Completed => StatusView::plain("completed").serialize(serializer),
            map::SourceStatus::Sampled => {
                StatusView::reason("sampled", "public_provider_sample").serialize(serializer)
            }
            map::SourceStatus::Skipped(map::SourceSkipReason::NotSitemap) => {
                StatusView::reason("skipped", "not_sitemap_html").serialize(serializer)
            }
            map::SourceStatus::Disabled => StatusView::plain("disabled").serialize(serializer),
            map::SourceStatus::NotStarted => StatusView::plain("not_started").serialize(serializer),
            map::SourceStatus::Truncated => StatusView::plain("truncated").serialize(serializer),
            map::SourceStatus::Failed(failure) => {
                StatusView::failure("failed", failure).serialize(serializer)
            }
        }
    }
}

pub(super) struct SupportDocumentsView<'a>(pub(super) &'a [map::SupportDocument]);

impl Serialize for SupportDocumentsView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut sequence = serializer.serialize_seq(Some(self.0.len()))?;
        for document in self.0 {
            sequence.serialize_element(&SupportDocumentView(document))?;
        }
        sequence.end()
    }
}

struct SupportDocumentView<'a>(&'a map::SupportDocument);

impl Serialize for SupportDocumentView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("SupportDocument", 3)?;
        state.serialize_field("url", self.0.url.as_str())?;
        state.serialize_field("kind", support_document_label(self.0.kind))?;
        state.serialize_field("status", &SourceStatusView(&self.0.status))?;
        state.end()
    }
}

pub(super) struct OmissionsView<'a>(pub(super) &'a [map::Omission]);

impl Serialize for OmissionsView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut sequence = serializer.serialize_seq(Some(self.0.len()))?;
        for omission in self.0 {
            sequence.serialize_element(&OmissionView(omission))?;
        }
        sequence.end()
    }
}

struct OmissionView<'a>(&'a map::Omission);

impl Serialize for OmissionView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("Omission", 2)?;
        state.serialize_field("reason", &OmissionReasonView(self.0.reason))?;
        state.serialize_field("count", &self.0.count)?;
        state.end()
    }
}

struct OmissionReasonView(map::OmissionReason);

impl Serialize for OmissionReasonView {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        match self.0 {
            map::OmissionReason::Admission(rejection) => {
                let mut state = serializer.serialize_struct("OmissionReason", 2)?;
                state.serialize_field("kind", "admission")?;
                state.serialize_field("rejection", rejection_label(rejection))?;
                state.end()
            }
            reason => reason_label(reason).serialize(serializer),
        }
    }
}

pub(super) struct FrontierView<'a>(pub(super) &'a [map::FrontierEntry]);

impl Serialize for FrontierView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut sequence = serializer.serialize_seq(Some(self.0.len()))?;
        for entry in self.0 {
            sequence.serialize_element(&FrontierEntryView(entry))?;
        }
        sequence.end()
    }
}

struct FrontierEntryView<'a>(&'a map::FrontierEntry);

impl Serialize for FrontierEntryView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("FrontierEntry", 2)?;
        state.serialize_field("page", self.0.page.as_str())?;
        state.serialize_field("reason", pending_reason_label(self.0.reason))?;
        state.end()
    }
}

pub(super) struct RequestTraceView<'a>(pub(super) &'a [map::RequestTrace]);

impl Serialize for RequestTraceView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut sequence = serializer.serialize_seq(Some(self.0.len()))?;
        for entry in self.0 {
            sequence.serialize_element(&RequestTraceEntryView(entry))?;
        }
        sequence.end()
    }
}

struct RequestTraceEntryView<'a>(&'a map::RequestTrace);

impl Serialize for RequestTraceEntryView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("RequestTraceEntry", 3)?;
        state.serialize_field("target", self.0.target.as_str())?;
        state.serialize_field("http_status", &self.0.status)?;
        state.serialize_field("charged_response_bytes", &self.0.charged_response_bytes)?;
        state.end()
    }
}
