use serde::{
    Deserialize, Deserializer, Serialize, Serializer,
    de::{Error as _, SeqAccess, Visitor},
    ser::Error as SerError,
};
use std::fmt;

use super::{
    Acquisition, AcquisitionKind, BrowserMode, DocumentRequest, MAX_ACQUISITIONS,
    MAX_DOCUMENTS_PER_ACQUISITION, Page,
};

impl Serialize for Acquisition {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        self.validate().map_err(SerError::custom)?;
        let wire = match self {
            Self::DirectHttp => AcquisitionWireOwned::DirectHttp {
                documents: DocumentSelectionWireOwned::Current,
            },
            Self::Browser(mode) => AcquisitionWireOwned::Browser {
                mode: *mode,
                documents: DocumentSelectionWireOwned::Current,
            },
            Self::Exact {
                acquisition: AcquisitionKind::DirectHttp,
                documents,
            } => AcquisitionWireOwned::DirectHttp {
                documents: DocumentSelectionWireOwned::Exact {
                    documents: documents.clone(),
                },
            },
            Self::Exact {
                acquisition: AcquisitionKind::Browser { mode },
                documents,
            } => AcquisitionWireOwned::Browser {
                mode: *mode,
                documents: DocumentSelectionWireOwned::Exact {
                    documents: documents.clone(),
                },
            },
        };
        wire.serialize(serializer)
    }
}

impl<'de> Deserialize<'de> for Acquisition {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let wire = AcquisitionWire::deserialize(deserializer)?;
        let acquisition = match wire {
            AcquisitionWire::DirectHttp {
                documents: DocumentSelectionWire::Current,
            } => Self::DirectHttp,
            AcquisitionWire::DirectHttp {
                documents: DocumentSelectionWire::Exact { documents },
            } => Self::DirectHttp.documents(documents.0),
            AcquisitionWire::Browser {
                mode,
                documents: DocumentSelectionWire::Current,
            } => Self::Browser(mode),
            AcquisitionWire::Browser {
                mode,
                documents: DocumentSelectionWire::Exact { documents },
            } => Self::Browser(mode).documents(documents.0),
        };
        acquisition.validate().map_err(D::Error::custom)?;
        Ok(acquisition)
    }
}

#[derive(Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum AcquisitionWireOwned {
    DirectHttp {
        documents: DocumentSelectionWireOwned,
    },
    Browser {
        mode: BrowserMode,
        documents: DocumentSelectionWireOwned,
    },
}

#[derive(Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum DocumentSelectionWireOwned {
    Current,
    Exact { documents: Vec<DocumentRequest> },
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum AcquisitionWire {
    DirectHttp {
        documents: DocumentSelectionWire,
    },
    Browser {
        mode: BrowserMode,
        documents: DocumentSelectionWire,
    },
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum DocumentSelectionWire {
    Current,
    Exact { documents: CappedDocuments },
}

struct CappedDocuments(Vec<DocumentRequest>);

impl<'de> Deserialize<'de> for CappedDocuments {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct CappedVisitor;

        impl<'de> Visitor<'de> for CappedVisitor {
            type Value = CappedDocuments;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("at most four document requests")
            }

            fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
            where
                A: SeqAccess<'de>,
            {
                let mut documents = Vec::with_capacity(MAX_DOCUMENTS_PER_ACQUISITION);
                while let Some(document) = sequence.next_element::<DocumentRequest>()? {
                    if documents.len() == MAX_DOCUMENTS_PER_ACQUISITION {
                        return Err(A::Error::custom(
                            "policy v2 permits at most four document requests per acquisition",
                        ));
                    }
                    documents.push(document);
                }
                Ok(CappedDocuments(documents))
            }
        }

        deserializer.deserialize_seq(CappedVisitor)
    }
}

impl Serialize for Page {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        self.validate().map_err(SerError::custom)?;
        PageWireRef {
            acquisitions: &self.acquisitions,
        }
        .serialize(serializer)
    }
}

impl<'de> Deserialize<'de> for Page {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let wire = PageWire::deserialize(deserializer)?;
        Self::new(wire.acquisitions.0).map_err(D::Error::custom)
    }
}

#[derive(Serialize)]
struct PageWireRef<'a> {
    acquisitions: &'a [Acquisition],
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PageWire {
    acquisitions: CappedAcquisitions,
}

struct CappedAcquisitions(Vec<Acquisition>);

impl<'de> Deserialize<'de> for CappedAcquisitions {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct CappedVisitor;

        impl<'de> Visitor<'de> for CappedVisitor {
            type Value = CappedAcquisitions;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("at most three page acquisitions")
            }

            fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
            where
                A: SeqAccess<'de>,
            {
                let mut acquisitions = Vec::with_capacity(MAX_ACQUISITIONS);
                while let Some(acquisition) = sequence.next_element::<Acquisition>()? {
                    if acquisitions.len() == MAX_ACQUISITIONS {
                        return Err(A::Error::custom(
                            "policy v2 permits at most three page acquisitions",
                        ));
                    }
                    acquisitions.push(acquisition);
                }
                Ok(CappedAcquisitions(acquisitions))
            }
        }

        deserializer.deserialize_seq(CappedVisitor)
    }
}
