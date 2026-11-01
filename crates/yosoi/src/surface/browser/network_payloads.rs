//! Surface-session body bounds and reachability from committed frozen windows.
use crate::surface::{
    NetworkObservationPolicy, NetworkPayloadRef, NetworkPayloadState, NetworkPayloadValue,
    NetworkRetention, SurfaceError,
};
use std::collections::{HashMap, HashSet, VecDeque};

pub(super) struct NetworkPayloadStore {
    payloads: HashMap<String, (NetworkPayloadValue, NetworkPayloadRef)>,
    windows: VecDeque<HashSet<String>>,
    retained_bytes: usize,
    maximum_bytes: usize,
    maximum_payloads: usize,
    maximum_windows: usize,
}

#[cfg(test)]
mod tests {
    use super::NetworkPayloadStore;
    use crate::{
        Document,
        surface::{
            NetworkByteProvenance, NetworkObservationPolicy, NetworkPayloadKind, NetworkPayloadRef,
            NetworkPayloadState, NetworkPayloadValue, NetworkProjectionBasis,
        },
    };
    use sha2::Digest;
    use std::error::Error;

    fn body(
        id: &str,
        bytes: &[u8],
    ) -> Result<(NetworkPayloadValue, NetworkPayloadRef), Box<dyn Error>> {
        let document = Document::json(id, bytes.to_vec())?;
        let reference = NetworkPayloadRef {
            id: id.into(),
            request_id: format!("request-{id}"),
            hop: 0,
            response_sequence: 1,
            response_window_id: format!("window-{id}"),
            body_capture_at_unix_us: Some(1),
            state: NetworkPayloadState::Retained,
            document_kind: Some(NetworkPayloadKind::Json),
            projection_basis: Some(NetworkProjectionBasis::RequestsDeclared),
            declared_media_type: Some("application/json".into()),
            browser_effective_mime: Some("application/json".into()),
            browser_effective_charset: Some("utf-8".into()),
            detected_media_type: Some("application/json".into()),
            content_encoding: None,
            byte_provenance: NetworkByteProvenance::CdpDecodedResponseBody,
            provider_base64_encoded: false,
            provider_reported_body_bytes: Some(document.byte_len()),
            text_utf8_normalized: true,
            retained_bytes: document.byte_len(),
            sha256: Some(format!("{:x}", sha2::Sha256::digest(bytes))),
            document_id: Some(id.into()),
            reason: None,
        };
        Ok((NetworkPayloadValue::Document(document), reference))
    }

    #[test]
    fn network_payload_store_survives_rearms_but_evicts_unreachable_windows()
    -> Result<(), Box<dyn Error>> {
        let initial = NetworkObservationPolicy {
            max_response_bodies: 2,
            max_total_body_bytes: 8,
            max_windows: 2,
            ..NetworkObservationPolicy::default()
        };
        let mut store = NetworkPayloadStore::new(&initial);
        let (first, first_ref) = body("first", b"[0]")?;
        store.insert(first, first_ref.clone())?;
        store.commit_window(std::slice::from_ref(&first_ref))?;
        let (second, second_ref) = body("second", b"[1]")?;
        store.insert(second, second_ref.clone())?;
        store.commit_window(&[first_ref.clone(), second_ref.clone()])?;
        for _ in 0..16 {
            store.discard_pending()?;
            let mut rearmed = NetworkObservationPolicy {
                max_response_bodies: 100,
                max_total_body_bytes: 1024,
                ..NetworkObservationPolicy::default()
            }
            .retention();
            store.apply_retention(&mut rearmed);
            assert_eq!(rearmed.max_response_bodies, 100);
            assert_eq!(rearmed.session_max_response_bodies, Some(2));
            assert_eq!(rearmed.session_max_total_body_bytes, Some(8));
            assert!(!store.can_retain(1));
            assert_eq!(store.payloads.len(), 2);
            assert_eq!(store.retained_bytes, 6);
            assert!(store.get(&first_ref.id).is_some());
        }
        store.commit_window(std::slice::from_ref(&second_ref))?;
        assert!(
            store.get(&first_ref.id).is_some(),
            "a second kept window still links the body"
        );
        store.commit_window(std::slice::from_ref(&second_ref))?;
        assert!(
            store.get(&first_ref.id).is_none(),
            "evicted frozen reference must become unreadable"
        );
        assert!(store.get(&second_ref.id).is_some());
        assert_eq!(store.retained_bytes, 3);
        assert!(store.can_retain(3));
        store.clear();
        assert!(store.get(&second_ref.id).is_none());
        assert_eq!(store.retained_bytes, 0);
        Ok(())
    }

    #[test]
    fn network_payload_store_bounds_bytes_and_discards_only_unpublished_bodies()
    -> Result<(), Box<dyn Error>> {
        let mut store = NetworkPayloadStore::new(&NetworkObservationPolicy {
            max_response_bodies: 10,
            max_total_body_bytes: 5,
            ..NetworkObservationPolicy::default()
        });
        let (kept, kept_ref) = body("kept", b"[0]")?;
        store.insert(kept, kept_ref.clone())?;
        store.commit_window(std::slice::from_ref(&kept_ref))?;
        assert!(
            !store.can_retain(3),
            "byte cap applies before the count cap"
        );
        let (pending, pending_ref) = body("pending", b"1")?;
        store.insert(pending, pending_ref.clone())?;
        assert_eq!(store.retained_bytes, 4);
        store.discard_pending()?;
        assert!(store.get(&kept_ref.id).is_some());
        assert!(store.get(&pending_ref.id).is_none());
        assert_eq!(store.retained_bytes, 3);
        Ok(())
    }
}

impl NetworkPayloadStore {
    pub(super) fn new(policy: &NetworkObservationPolicy) -> Self {
        Self {
            payloads: HashMap::new(),
            windows: VecDeque::new(),
            retained_bytes: 0,
            maximum_bytes: policy.max_total_body_bytes,
            maximum_payloads: policy.max_response_bodies,
            maximum_windows: policy.max_windows,
        }
    }

    pub(super) fn can_retain(&self, bytes: usize) -> bool {
        self.payloads.len() < self.maximum_payloads
            && self
                .retained_bytes
                .checked_add(bytes)
                .is_some_and(|total| total <= self.maximum_bytes)
    }

    pub(super) fn insert(
        &mut self,
        payload: NetworkPayloadValue,
        reference: NetworkPayloadRef,
    ) -> Result<(), SurfaceError> {
        if self.payloads.contains_key(&reference.id) || !self.can_retain(payload.bytes().len()) {
            return Err(SurfaceError::Limit("network session payload retention"));
        }
        self.retained_bytes = self
            .retained_bytes
            .checked_add(payload.bytes().len())
            .ok_or(SurfaceError::Limit("network session payload bytes"))?;
        self.payloads
            .insert(reference.id.clone(), (payload, reference));
        Ok(())
    }

    pub(super) fn get(&self, id: &str) -> Option<&(NetworkPayloadValue, NetworkPayloadRef)> {
        self.payloads.get(id)
    }

    pub(super) const fn apply_retention(&self, retention: &mut NetworkRetention) {
        retention.session_max_response_bodies = Some(self.maximum_payloads);
        retention.session_max_total_body_bytes = Some(self.maximum_bytes);
    }

    pub(super) fn summary(&self) -> serde_json::Value {
        serde_json::json!({
            "session_max_response_bodies": self.maximum_payloads,
            "session_max_total_body_bytes": self.maximum_bytes,
            "session_retained_response_bodies": self.payloads.len(),
            "session_retained_body_bytes": self.retained_bytes,
        })
    }

    /// Called synchronously with Driver's successful publication/history eviction.
    pub(super) fn commit_window(
        &mut self,
        references: &[NetworkPayloadRef],
    ) -> Result<(), SurfaceError> {
        let mut reachable = HashSet::new();
        for reference in references {
            if !matches!(
                reference.state,
                NetworkPayloadState::Retained | NetworkPayloadState::Truncated
            ) {
                continue;
            }
            if !self
                .get(&reference.id)
                .is_some_and(|(_, stored)| stored == reference)
            {
                return Err(SurfaceError::Invalid(
                    "frozen network window lacks its exact body".into(),
                ));
            }
            reachable.insert(reference.id.clone());
        }
        self.windows.push_back(reachable);
        while self.windows.len() > self.maximum_windows {
            self.windows.pop_front();
        }
        self.discard_pending()
    }

    /// Discard bodies from failed/unpublished captures while preserving kept windows.
    pub(super) fn discard_pending(&mut self) -> Result<(), SurfaceError> {
        self.payloads
            .retain(|id, _| self.windows.iter().any(|window| window.contains(id)));
        self.retained_bytes = self
            .payloads
            .values()
            .try_fold(0_usize, |total, (payload, _)| {
                total.checked_add(payload.bytes().len())
            })
            .ok_or(SurfaceError::Limit("network session payload bytes"))?;
        Ok(())
    }

    pub(super) fn clear(&mut self) {
        self.payloads.clear();
        self.windows.clear();
        self.retained_bytes = 0;
    }
}
