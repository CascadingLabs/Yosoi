use std::fmt;

use thiserror::Error;
use yosoi_archive::{
    ArchiveError, CaptureArchiveRef, DocumentArchiveRef, PolicyArchiveRef, RequestRunArchiveRef,
    RequestRunRecord, RequestRunRecordError,
};
use yosoi_types::CaptureId;

use crate::RequestId;

use super::{AttemptCaptureFacts, RequestSendError, Response};

/// Response plus the durable entrypoints produced by an explicit archived send.
pub struct ArchivedResponse {
    response: Response,
    policy: PolicyArchiveRef,
    request_run: RequestRunArchiveRef,
}

impl ArchivedResponse {
    pub(crate) const fn new(
        response: Response,
        policy: PolicyArchiveRef,
        request_run: RequestRunArchiveRef,
    ) -> Self {
        Self {
            response,
            policy,
            request_run,
        }
    }

    pub const fn response(&self) -> &Response {
        &self.response
    }

    pub const fn policy_ref(&self) -> &PolicyArchiveRef {
        &self.policy
    }

    pub const fn request_run_ref(&self) -> &RequestRunArchiveRef {
        &self.request_run
    }

    pub fn into_parts(self) -> (Response, PolicyArchiveRef, RequestRunArchiveRef) {
        (self.response, self.policy, self.request_run)
    }
}

impl fmt::Debug for ArchivedResponse {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ArchivedResponse")
            .field("response", &self.response)
            .field("policy", &self.policy)
            .field("request_run", &self.request_run)
            .finish()
    }
}

/// Durable references committed before an archived request either finishes or fails.
#[derive(Clone, Debug)]
pub struct ArchivedRequestProgress {
    policy: PolicyArchiveRef,
    captures: Vec<ArchivedCaptureProgress>,
}

impl ArchivedRequestProgress {
    pub(crate) const fn new(policy: PolicyArchiveRef) -> Self {
        Self {
            policy,
            captures: Vec::new(),
        }
    }

    pub const fn policy_ref(&self) -> &PolicyArchiveRef {
        &self.policy
    }

    pub fn captures(&self) -> &[ArchivedCaptureProgress] {
        &self.captures
    }

    pub(crate) fn commit_capture(&mut self, capture: CaptureArchiveRef) {
        self.captures.push(ArchivedCaptureProgress {
            capture,
            documents: Vec::new(),
        });
    }

    pub(crate) fn commit_document(
        &mut self,
        capture: &CaptureArchiveRef,
        document: DocumentArchiveRef,
    ) {
        if let Some(progress) = self
            .captures
            .iter_mut()
            .rev()
            .find(|progress| &progress.capture == capture)
        {
            progress.documents.push(document);
        }
    }
}

/// One committed Capture and the normalized Documents already published from it.
#[derive(Clone, Debug)]
pub struct ArchivedCaptureProgress {
    capture: CaptureArchiveRef,
    documents: Vec<DocumentArchiveRef>,
}

impl ArchivedCaptureProgress {
    pub const fn capture_ref(&self) -> &CaptureArchiveRef {
        &self.capture
    }

    pub fn document_refs(&self) -> &[DocumentArchiveRef] {
        &self.documents
    }
}

/// Typed failures unique to the explicit archived-request path.
#[derive(Debug, Error)]
pub enum ArchivedRequestError {
    #[error(transparent)]
    Send(#[from] RequestSendError),
    #[error("failed to publish the Policy for request {request_id}")]
    PolicyPublication {
        request_id: RequestId,
        #[source]
        source: Box<ArchiveError>,
    },
    #[error(
        "failed to publish capture {capture_id} for request {request_id} attempt {attempt_index}"
    )]
    CapturePublication {
        request_id: RequestId,
        attempt_index: u64,
        capture_id: CaptureId,
        progress: Box<ArchivedRequestProgress>,
        capture_facts: Box<AttemptCaptureFacts>,
        #[source]
        source: Box<ArchiveError>,
    },
    #[error(
        "failed to publish Document {document_index} for request {request_id} attempt {attempt_index}"
    )]
    DocumentPublication {
        request_id: RequestId,
        attempt_index: u64,
        document_index: u64,
        progress: Box<ArchivedRequestProgress>,
        #[source]
        source: Box<ArchiveError>,
    },
    #[error("request {request_id} could not be projected into a valid durable request-run record")]
    InvalidRequestRunRecord {
        request_id: RequestId,
        progress: Box<ArchivedRequestProgress>,
        #[source]
        source: Box<RequestRunRecordError>,
    },
    #[error(
        "archived request {request_id} attempt {capture_id} lost its committed Capture reference"
    )]
    MissingCaptureReference {
        request_id: RequestId,
        capture_id: CaptureId,
    },
    #[error("request completed but its durable request-run record could not be published")]
    RequestRunPublication {
        response: Box<Response>,
        pending_record: Box<RequestRunRecord>,
        #[source]
        source: Box<ArchiveError>,
    },
}
