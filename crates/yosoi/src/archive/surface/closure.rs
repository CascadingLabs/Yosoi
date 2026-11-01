use super::{Archive, ArchiveError};
use crate::internal::archive::{DocumentArchiveRef, FileDocumentArchiveRef};
use crate::{
    documents::{Document, DocumentProfile, FileDocument},
    surface::{ArchivedFileKind, ArchivedSource, Outcome},
};
use base64::{Engine, engine::general_purpose::STANDARD};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fmt::Display,
};

#[derive(Clone, Copy)]
enum DependencyKind {
    Document,
    FileDocument,
}

struct Dependency {
    pointer: &'static str,
    kind: DependencyKind,
    reference: String,
}

/// Registered schema fields whose Archive references are dependencies of a source Document.
/// Arbitrary strings and unrecognized JSON schemas are never scanned.
fn dependencies(document: &Document) -> Result<Vec<Dependency>, ArchiveError> {
    if document.profile() != DocumentProfile::source_json() {
        return Ok(Vec::new());
    }
    let value: Value = serde_json::from_slice(document.bytes()).map_err(invalid)?;
    let schema = value
        .get("schema")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let fields: &[(&str, DependencyKind)] = match schema {
        "yosoi.surface.video-source.v2" => &[("/source", DependencyKind::FileDocument)],
        "yosoi.surface.video-frame.v2" => &[("/pixels/document", DependencyKind::Document)],
        "yosoi.pixel-artifact.v1" => &[("/image", DependencyKind::FileDocument)],
        _ => return Ok(Vec::new()),
    };
    fields
        .iter()
        .map(|(pointer, kind)| {
            let reference = value
                .pointer(pointer)
                .and_then(Value::as_str)
                .ok_or_else(|| invalid(format!("registered dependency {pointer} is missing")))?;
            Ok(Dependency {
                pointer,
                kind: *kind,
                reference: reference.to_owned(),
            })
        })
        .collect()
}

fn has_source_alias(value: &Outcome, reference: &str) -> bool {
    value.sources.iter().any(|source| {
        source.key == reference
            || source
                .document_archive
                .as_ref()
                .is_some_and(|candidate| candidate.to_string() == reference)
            || source
                .file_archive
                .as_ref()
                .is_some_and(|candidate| candidate.to_string() == reference)
    })
}

/// Materializes only known schema dependencies into the self-contained Outcome source set.
async fn close_dependencies(archive: &Archive, value: &mut Outcome) -> Result<(), ArchiveError> {
    let mut visited = BTreeSet::new();
    loop {
        let mut missing = Vec::<(String, DependencyKind)>::new();
        for source in &value.sources {
            if source.file_kind.is_some() || source.profile.is_none() {
                continue;
            }
            let document = source.restore(value.limits.bytes).map_err(invalid)?;
            for dependency in dependencies(&document)? {
                if !has_source_alias(value, &dependency.reference)
                    && visited.insert(dependency.reference.clone())
                {
                    missing.push((dependency.reference, dependency.kind));
                }
            }
        }
        if missing.is_empty() {
            return Ok(());
        }
        if value.sources.len().saturating_add(missing.len()) > value.limits.observations {
            return Err(invalid(
                "Archive dependency closure exceeds outcome source limit",
            ));
        }
        for (reference, kind) in missing {
            match kind {
                DependencyKind::Document => {
                    let reference: DocumentArchiveRef = reference.parse().map_err(invalid)?;
                    let document = match archive.read_document(&reference).await {
                        Ok(document) => document,
                        Err(
                            ArchiveError::RecordNotFound { .. }
                            | ArchiveError::DocumentPayloadMissing { .. },
                        ) => {
                            value.complete = false;
                            continue;
                        }
                        Err(error) => return Err(error),
                    };
                    let mut source = ArchivedSource::new(reference.to_string(), &document, None);
                    source.document_archive = Some(reference);
                    value.sources.push(source);
                }
                DependencyKind::FileDocument => {
                    let reference: FileDocumentArchiveRef = reference.parse().map_err(invalid)?;
                    let file: FileDocument = match archive.read(&reference).await {
                        Ok(file) => file,
                        Err(
                            ArchiveError::RecordNotFound { .. }
                            | ArchiveError::DocumentPayloadMissing { .. },
                        ) => {
                            value.complete = false;
                            continue;
                        }
                        Err(error) => return Err(error),
                    };
                    let mut source =
                        ArchivedSource::new_file_document(reference.to_string(), &file, None);
                    source.file_archive = Some(reference);
                    value.sources.push(source);
                }
            }
        }
    }
}

fn rewrite_document(
    document: &Document,
    file_references: &BTreeMap<String, String>,
    document_references: &BTreeMap<String, String>,
) -> Result<Option<Document>, ArchiveError> {
    let dependencies = dependencies(document)?;
    if dependencies.is_empty() {
        return Ok(Some(document.clone()));
    }
    let mut value: Value = serde_json::from_slice(document.bytes()).map_err(invalid)?;
    let mut changed = false;
    for dependency in dependencies {
        let remapped = match dependency.kind {
            DependencyKind::Document => document_references.get(&dependency.reference),
            DependencyKind::FileDocument => file_references.get(&dependency.reference),
        };
        let Some(remapped) = remapped else {
            return Ok(None);
        };
        let target = value
            .pointer_mut(dependency.pointer)
            .ok_or_else(|| invalid("registered dependency pointer disappeared"))?;
        if target.as_str() != Some(remapped) {
            *target = Value::String(remapped.clone());
            changed = true;
        }
    }
    if !changed {
        return Ok(Some(document.clone()));
    }
    let bytes = serde_json::to_vec(&value).map_err(invalid)?;
    Document::from_profile(document.id().clone(), document.profile(), bytes)
        .map(Some)
        .map_err(|error| invalid(error.to_string()))
}

fn add_aliases(
    references: &mut BTreeMap<String, String>,
    source: &ArchivedSource,
    fresh: &str,
    previous: Option<String>,
) {
    references.insert(source.key.clone(), fresh.to_owned());
    if let Some(previous) = previous {
        references.insert(previous, fresh.to_owned());
    }
}

pub(super) async fn rehydrate(archive: &Archive, value: &mut Outcome) -> Result<(), ArchiveError> {
    close_dependencies(archive, value).await?;
    value.validate().map_err(invalid)?;
    let file_references = rehydrate_files(archive, value).await?;
    let document_references = rehydrate_documents(archive, value, &file_references).await?;
    rehydrate_receipts(value, &file_references, &document_references)
}

async fn rehydrate_files(
    archive: &Archive,
    value: &mut Outcome,
) -> Result<BTreeMap<String, String>, ArchiveError> {
    let mut file_references = BTreeMap::new();
    for source in &mut value.sources {
        if source.file_kind.is_none() {
            continue;
        }
        let previous = source.file_archive.as_ref().map(ToString::to_string);
        let file = source
            .restore_file_document(value.limits.bytes)
            .map_err(invalid)?;
        let reference = match source.file_archive.as_ref() {
            Some(existing) => match archive.read(existing).await {
                Ok(saved) if saved == file => existing.clone(),
                Ok(_)
                | Err(
                    ArchiveError::RecordNotFound { .. }
                    | ArchiveError::DocumentPayloadMissing { .. },
                ) => archive.write(&file).await?,
                Err(error) => return Err(error),
            },
            None => archive.write(&file).await?,
        };
        let fresh = reference.to_string();
        add_aliases(&mut file_references, source, &fresh, previous);
        source.file_archive = Some(reference);
        source.content_base64 = None;
    }

    Ok(file_references)
}

async fn rehydrate_documents(
    archive: &Archive,
    value: &mut Outcome,
    file_references: &BTreeMap<String, String>,
) -> Result<BTreeMap<String, String>, ArchiveError> {
    let mut document_references = BTreeMap::new();
    let mut pending: BTreeSet<usize> = value
        .sources
        .iter()
        .enumerate()
        .filter_map(|(index, source)| source.profile.map(|_| index))
        .collect();
    while !pending.is_empty() {
        let mut completed = Vec::new();
        for index in &pending {
            let source = value
                .sources
                .get(*index)
                .ok_or_else(|| invalid("outcome source index disappeared"))?;
            let previous = source.document_archive.as_ref().map(ToString::to_string);
            let document = source.restore(value.limits.bytes).map_err(invalid)?;
            let Some(document) =
                rewrite_document(&document, file_references, &document_references)?
            else {
                continue;
            };
            let reference = match source.document_archive.as_ref() {
                Some(existing) => match archive.read_document(existing).await {
                    Ok(saved) if saved == document => existing.clone(),
                    Ok(_)
                    | Err(
                        ArchiveError::RecordNotFound { .. }
                        | ArchiveError::DocumentPayloadMissing { .. },
                    ) => archive.write_document(&document).await?,
                    Err(error) => return Err(error),
                },
                None => archive.write_document(&document).await?,
            };
            let fresh = reference.to_string();
            let source = value
                .sources
                .get_mut(*index)
                .ok_or_else(|| invalid("outcome source index disappeared"))?;
            add_aliases(&mut document_references, source, &fresh, previous);
            source.document_archive = Some(reference);
            source.sha256 = format!("{:x}", Sha256::digest(document.bytes()));
            source.content_base64 = None;
            completed.push(*index);
        }
        if completed.is_empty() {
            if value.complete {
                return Err(invalid(
                    "registered Archive Document dependencies are missing or cyclic",
                ));
            }
            for index in pending.iter().copied() {
                let source = value
                    .sources
                    .get(index)
                    .ok_or_else(|| invalid("outcome source index disappeared"))?;
                let previous = source.document_archive.as_ref().map(ToString::to_string);
                let document = source.restore(value.limits.bytes).map_err(invalid)?;
                let reference = match source.document_archive.as_ref() {
                    Some(existing) => match archive.read_document(existing).await {
                        Ok(saved) if saved == document => existing.clone(),
                        _ => archive.write_document(&document).await?,
                    },
                    None => archive.write_document(&document).await?,
                };
                let fresh = reference.to_string();
                let source = value
                    .sources
                    .get_mut(index)
                    .ok_or_else(|| invalid("outcome source index disappeared"))?;
                add_aliases(&mut document_references, source, &fresh, previous);
                source.document_archive = Some(reference);
                source.sha256 = format!("{:x}", Sha256::digest(document.bytes()));
                source.content_base64 = None;
            }
            break;
        }
        for index in completed {
            pending.remove(&index);
        }
    }

    Ok(document_references)
}

fn rehydrate_receipts(
    value: &mut Outcome,
    file_references: &BTreeMap<String, String>,
    document_references: &BTreeMap<String, String>,
) -> Result<(), ArchiveError> {
    let mut wire = serde_json::to_value(&value.record).map_err(invalid)?;
    let operations = wire
        .get_mut("operations")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| invalid("missing record operations"))?;
    for operation in operations {
        let kind = operation
            .get("kind")
            .and_then(Value::as_str)
            .unwrap_or_default();
        if kind == "surface.command"
            && operation
                .pointer("/result/command/op")
                .and_then(Value::as_str)
                == Some("screenshot")
        {
            let reference = operation.pointer_mut("/result/outcome/archive_ref/document");
            if let Some(reference) = reference {
                let key = reference
                    .as_str()
                    .ok_or_else(|| invalid("screenshot pixel reference is not text"))?;
                if let Some(fresh) = document_references.get(key) {
                    *reference = Value::String(fresh.clone());
                } else if value.complete {
                    return Err(invalid(
                        "portable screenshot artifact dependency is missing",
                    ));
                }
            }
            continue;
        }
        if !matches!(
            kind,
            "surface.capture" | "surface.video.source" | "surface.video.frame"
        ) {
            continue;
        }
        let Some(reference) = operation.pointer_mut("/result/document") else {
            if value.complete {
                return Err(invalid("missing retained document reference"));
            }
            continue;
        };
        let key = reference
            .as_str()
            .ok_or_else(|| invalid("document reference is not text"))?;
        let fresh = document_references
            .get(key)
            .or_else(|| file_references.get(key));
        if let Some(fresh) = fresh {
            *reference = Value::String(fresh.clone());
        } else if value.complete {
            return Err(invalid("portable outcome is missing a retained dependency"));
        }
    }
    value.record = serde_json::from_value(wire).map_err(invalid)?;
    Ok(())
}

pub(super) async fn hydrate(archive: &Archive, value: &mut Outcome) -> Result<(), ArchiveError> {
    for source in &mut value.sources {
        if let Some(reference) = source.document_archive.as_ref() {
            let document = archive.read_document(reference).await?;
            if source.document != *document.id()
                || source
                    .profile
                    .is_some_and(|profile| profile != document.profile())
                || source.sha256 != format!("{:x}", Sha256::digest(document.bytes()))
            {
                return Err(invalid("archived Document source metadata mismatch"));
            }
            source.profile = Some(document.profile());
            source.content_base64 = Some(STANDARD.encode(document.bytes()));
        }
        if let Some(reference) = source.file_archive.as_ref() {
            let file = archive.read(reference).await?;
            let file_kind = match &file {
                FileDocument::Image(_) => ArchivedFileKind::Image,
                FileDocument::Video(_) => ArchivedFileKind::Video,
                FileDocument::Audio(_) => ArchivedFileKind::Audio,
                FileDocument::Binary(_) => ArchivedFileKind::Binary,
            };
            if source.document != *file.id()
                || source.file_kind.is_some_and(|kind| kind != file_kind)
                || source
                    .file_metadata
                    .as_ref()
                    .is_some_and(|metadata| metadata != file.metadata())
                || source.sha256 != file.sha256()
            {
                return Err(invalid("archived FileDocument source metadata mismatch"));
            }
            source.file_kind = Some(file_kind);
            source.file_metadata = Some(file.metadata().clone());
            source.content_base64 = Some(STANDARD.encode(file.bytes()));
        }
    }
    close_dependencies(archive, value).await?;
    value.validate().map_err(invalid)?;
    Ok(())
}

fn invalid(error: impl Display) -> ArchiveError {
    ArchiveError::InvalidSurfaceOutcome(error.to_string())
}
