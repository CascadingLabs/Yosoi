use serde::{
    Serialize, Serializer,
    ser::{SerializeSeq, SerializeStruct},
};
use yosoi::map;

use super::super::wire::{
    StatusView, discovery_source_label, host_verification_label, relationship_kind_label,
    skip_reason_label,
};

pub(super) struct HostsView<'a>(pub(super) &'a [map::HostEntry]);

impl Serialize for HostsView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut sequence = serializer.serialize_seq(Some(self.0.len()))?;
        for host in self.0 {
            sequence.serialize_element(&HostView(host))?;
        }
        sequence.end()
    }
}

struct HostView<'a>(&'a map::HostEntry);

impl Serialize for HostView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("Host", 3)?;
        state.serialize_field("host", &self.0.host)?;
        state.serialize_field("verification", host_verification_label(self.0.verification))?;
        state.serialize_field("observations", &ObservationsView(&self.0.observations))?;
        state.end()
    }
}

struct ObservationsView<'a>(&'a [map::Observation]);

impl Serialize for ObservationsView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut sequence = serializer.serialize_seq(Some(self.0.len()))?;
        for observation in self.0 {
            sequence.serialize_element(&ObservationView(observation))?;
        }
        sequence.end()
    }
}

struct ObservationView<'a>(&'a map::Observation);

impl Serialize for ObservationView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("Observation", 2)?;
        state.serialize_field("source", discovery_source_label(self.0.source))?;
        state.serialize_field(
            "source_url",
            &self.0.source_url.as_ref().map(AsRef::<str>::as_ref),
        )?;
        state.end()
    }
}

pub(super) struct PagesView<'a>(pub(super) &'a [map::PageEntry]);

impl Serialize for PagesView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut sequence = serializer.serialize_seq(Some(self.0.len()))?;
        for page in self.0 {
            sequence.serialize_element(&PageView(page))?;
        }
        sequence.end()
    }
}

struct PageView<'a>(&'a map::PageEntry);

impl Serialize for PageView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("Page", 4)?;
        state.serialize_field("url", self.0.url.as_str())?;
        state.serialize_field("minimum_link_depth", &self.0.minimum_link_depth)?;
        state.serialize_field("exploration", &ExplorationView(&self.0.exploration))?;
        state.serialize_field("observations", &ObservationsView(&self.0.observations))?;
        state.end()
    }
}

struct ExplorationView<'a>(&'a map::Exploration);

impl Serialize for ExplorationView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        match self.0 {
            map::Exploration::Inventoried => StatusView::plain("inventoried").serialize(serializer),
            map::Exploration::Pending => StatusView::plain("pending").serialize(serializer),
            map::Exploration::Inspected => StatusView::plain("inspected").serialize(serializer),
            map::Exploration::Skipped(reason) => {
                StatusView::reason("skipped", skip_reason_label(*reason)).serialize(serializer)
            }
            map::Exploration::Failed(failure) => {
                StatusView::failure("failed", failure).serialize(serializer)
            }
        }
    }
}

pub(super) struct RelationshipsView<'a>(pub(super) &'a [map::Relationship]);

impl Serialize for RelationshipsView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut sequence = serializer.serialize_seq(Some(self.0.len()))?;
        for relationship in self.0 {
            sequence.serialize_element(&RelationshipView(relationship))?;
        }
        sequence.end()
    }
}

struct RelationshipView<'a>(&'a map::Relationship);

impl Serialize for RelationshipView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("Relationship", 3)?;
        state.serialize_field("from", self.0.from.as_str())?;
        state.serialize_field("to", self.0.to.as_str())?;
        state.serialize_field("kind", relationship_kind_label(self.0.kind))?;
        state.end()
    }
}

pub(super) struct TreeView<'a>(pub(super) &'a [map::TreeEntry]);

impl Serialize for TreeView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut sequence = serializer.serialize_seq(Some(self.0.len()))?;
        for entry in self.0 {
            sequence.serialize_element(&TreeEntryView(entry))?;
        }
        sequence.end()
    }
}

struct TreeEntryView<'a>(&'a map::TreeEntry);

impl Serialize for TreeEntryView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("TreeEntry", 3)?;
        state.serialize_field("url", self.0.page.as_str())?;
        state.serialize_field("parent", &self.0.parent.as_ref().map(AsRef::<str>::as_ref))?;
        state.serialize_field("depth", &self.0.depth)?;
        state.end()
    }
}

pub(super) struct WildcardsView<'a>(pub(super) &'a [map::WildcardEntry]);

impl Serialize for WildcardsView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut sequence = serializer.serialize_seq(Some(self.0.len()))?;
        for entry in self.0 {
            sequence.serialize_element(&WildcardView(entry))?;
        }
        sequence.end()
    }
}

struct WildcardView<'a>(&'a map::WildcardEntry);

impl Serialize for WildcardView<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("Wildcard", 2)?;
        state.serialize_field("pattern", &self.0.pattern)?;
        state.serialize_field("observations", &ObservationsView(&self.0.observations))?;
        state.end()
    }
}
