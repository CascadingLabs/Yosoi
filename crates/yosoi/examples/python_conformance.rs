//! Machine-readable public Rust results for cross-language conformance.

use serde_json::{Value, json};
use std::{
    error::Error,
    io::{self, Read},
};
use yosoi::{
    contracts::{
        ContractSchema, ContractValue, RuntimeContract, RuntimeContractOutcome, RuntimeFieldValue,
        RuntimeValue,
    },
    documents::{
        AudioDocument, BinaryDocument, DEFAULT_FILE_MAX_BYTES, Document, DocumentId,
        DocumentProfile, FileDocument, FileDocumentError, FileLimits, FileMetadata, ImageDocument,
        MAX_FILE_BYTES, VideoDocument, file_from_bytes,
    },
    locators::{Plan, QuerySpec, TreeCoordinate, css, xpath},
    map::{MapTermination, Summary},
    policy::{
        Filters as PolicyFilters, Map as PolicyMap, ObserveLimits, ObservePolicy, Policy,
        PolicyError, PolicySnapshot, RecordingRule, observe::MAX_RECORDING_DURATION_MS,
    },
    search::SearchHitMetadata,
};

fn file_metadata(value: &Value) -> Result<FileMetadata, Box<dyn Error>> {
    let mut metadata = FileMetadata::new();
    if let Some(value) = value.get("filename").and_then(Value::as_str) {
        metadata = metadata.with_filename(value.to_owned())?;
    }
    if let Some(value) = value.get("declared_media_type").and_then(Value::as_str) {
        metadata = metadata.with_declared_media_type(value.to_owned())?;
    }
    if let Some(value) = value.get("source").and_then(Value::as_str) {
        metadata = metadata.with_source(value.to_owned())?;
    }
    if let Some(value) = value.get("capture_id").and_then(Value::as_str) {
        metadata = metadata.with_capture_id(value.to_owned())?;
    }
    if let Some(value) = value.get("session_id").and_then(Value::as_str) {
        metadata = metadata.with_session_id(value.to_owned())?;
    }
    if let Some(value) = value.get("tab_id").and_then(Value::as_str) {
        metadata = metadata.with_tab_id(value.to_owned())?;
    }
    if let Some(value) = value.get("download_id").and_then(Value::as_str) {
        metadata = metadata.with_download_id(value.to_owned())?;
    }
    Ok(metadata)
}

fn file_bytes(value: &Value) -> Result<Vec<u8>, Box<dyn Error>> {
    let values = value.as_array().ok_or("file bytes missing")?;
    let mut bytes = Vec::with_capacity(values.len());
    for value in values {
        let byte = value
            .as_u64()
            .ok_or_else(|| io::Error::other("file byte is not an unsigned integer"))?;
        bytes.push(u8::try_from(byte).map_err(|_| io::Error::other("file byte exceeds u8"))?);
    }
    Ok(bytes)
}

const fn file_kind(file: &FileDocument) -> &'static str {
    match file {
        FileDocument::Image(_) => "image",
        FileDocument::Video(_) => "video",
        FileDocument::Audio(_) => "audio",
        FileDocument::Binary(_) => "binary",
    }
}

fn file_value(file: &FileDocument, maximum_bytes: u64) -> Value {
    json!({
        "id": file.id().as_str(),
        "kind": file_kind(file),
        "bytes": file.bytes(),
        "byte_len": file.byte_len(),
        "sha256": file.sha256(),
        "metadata": file.metadata(),
        "maximum_bytes": maximum_bytes,
        "default_file_max_bytes": DEFAULT_FILE_MAX_BYTES,
        "max_file_bytes": MAX_FILE_BYTES,
        "max_recording_duration_ms": MAX_RECORDING_DURATION_MS,
    })
}

fn typed_file_document(
    family: &str,
    constructor: &str,
    id: String,
    bytes: Vec<u8>,
    metadata: FileMetadata,
    maximum_bytes: u64,
) -> Result<FileDocument, Box<dyn Error>> {
    let limits = FileLimits::new(maximum_bytes)?;
    Ok(match (family, constructor) {
        ("image", "default") => FileDocument::Image(ImageDocument::from_bytes(id, bytes)?),
        ("image", "limits") => {
            FileDocument::Image(ImageDocument::from_bytes_with_limits(id, bytes, limits)?)
        }
        ("image", "metadata") => FileDocument::Image(ImageDocument::from_bytes_with_metadata(
            id, bytes, metadata, limits,
        )?),
        ("video", "default") => FileDocument::Video(VideoDocument::from_bytes(id, bytes)?),
        ("video", "limits") => {
            FileDocument::Video(VideoDocument::from_bytes_with_limits(id, bytes, limits)?)
        }
        ("video", "metadata") => FileDocument::Video(VideoDocument::from_bytes_with_metadata(
            id, bytes, metadata, limits,
        )?),
        ("audio", "default") => FileDocument::Audio(AudioDocument::from_bytes(id, bytes)?),
        ("audio", "limits") => {
            FileDocument::Audio(AudioDocument::from_bytes_with_limits(id, bytes, limits)?)
        }
        ("audio", "metadata") => FileDocument::Audio(AudioDocument::from_bytes_with_metadata(
            id, bytes, metadata, limits,
        )?),
        ("binary", "default") => FileDocument::Binary(BinaryDocument::from_bytes(id, bytes)?),
        ("binary", "limits") => {
            FileDocument::Binary(BinaryDocument::from_bytes_with_limits(id, bytes, limits)?)
        }
        ("binary", "metadata") => FileDocument::Binary(BinaryDocument::from_bytes_with_metadata(
            id, bytes, metadata, limits,
        )?),
        _ => return Err("unknown typed file-document family or constructor".into()),
    })
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input)?;
    let cases: Vec<Value> = serde_json::from_str(&input)?;
    let mut results = Vec::new();
    for case in cases {
        let kind = case
            .get("kind")
            .and_then(Value::as_str)
            .ok_or("case kind missing")?;
        let name = case
            .get("name")
            .and_then(Value::as_str)
            .ok_or("case name missing")?;
        let result = match kind {
            "contract_value_identity" => {
                struct CustomValue;
                impl ContractValue for CustomValue {
                    const TYPE_ID: &'static str = "custom.review";
                }
                struct EmptyIdentity;
                impl ContractValue for EmptyIdentity {
                    const TYPE_ID: &'static str = "";
                }
                json!({
                    "string": <String as ContractValue>::TYPE_ID,
                    "custom": <CustomValue as ContractValue>::TYPE_ID,
                    "empty": <EmptyIdentity as ContractValue>::TYPE_ID,
                })
            }
            "wire_view" => {
                let value = match name {
                    "tree-required-null" => {
                        serde_json::to_value(TreeCoordinate::try_new(vec![1], None)?)?
                    }
                    "query-absent-namespaces" => serde_json::to_value(css("article")?)?,
                    "query-present-namespaces" => {
                        serde_json::to_value(xpath("//p:name")?.with_namespace("p", "urn:test")?)?
                    }
                    "map-unit-termination" => serde_json::to_value(MapTermination::Exhausted)?,
                    "runtime-optional-null" => {
                        serde_json::to_value(RuntimeFieldValue::ZeroOrOne { value: None })?
                    }
                    _ => return Err("unknown wire-view case".into()),
                };
                json!({"value": value})
            }
            "model_clone" => {
                let type_name = case
                    .get("rust_type")
                    .and_then(Value::as_str)
                    .ok_or("clone type missing")?;
                let marker = case
                    .get("marker")
                    .and_then(Value::as_str)
                    .ok_or("clone marker missing")?;
                match type_name {
                    "yosoi::Policy" => {
                        let original = Policy::default();
                        let mut cloned = original.clone();
                        cloned
                            .map
                            .filters
                            .excluded_query_keys
                            .push(marker.to_owned());
                        json!({"original": original, "clone": cloned})
                    }
                    "yosoi::policy::Map" => {
                        let original = PolicyMap::default();
                        let mut cloned = original.clone();
                        cloned.filters.excluded_query_keys.push(marker.to_owned());
                        json!({"original": original, "clone": cloned})
                    }
                    "yosoi::policy::Filters" => {
                        let original = PolicyFilters::default();
                        let mut cloned = original.clone();
                        cloned.excluded_query_keys.push(marker.to_owned());
                        json!({"original": original, "clone": cloned})
                    }
                    _ => return Err("unknown clone type".into()),
                }
            }
            "model_default" => {
                let type_name = case
                    .get("rust_type")
                    .and_then(Value::as_str)
                    .ok_or("model type missing")?;
                let value = default_model(type_name)?;
                let fields = if type_name == "yosoi::Policy" {
                    json!({"tuning": Policy::default().tuning})
                } else {
                    json!({})
                };
                json!({"value": value, "omitted_fields": fields})
            }
            "query" => {
                let source: QuerySpec = serde_json::from_value(
                    case.get("query").ok_or("query source missing")?.clone(),
                )?;
                let operation = case
                    .get("operation")
                    .and_then(Value::as_str)
                    .ok_or("query operation missing")?;
                let query = match operation {
                    "new" => Ok(QuerySpec::new(source.atom().clone(), source.result_shape())),
                    "with_namespace" => source.with_namespace(
                        case.get("prefix")
                            .and_then(Value::as_str)
                            .ok_or("namespace prefix missing")?,
                        case.get("uri")
                            .and_then(Value::as_str)
                            .ok_or("namespace URI missing")?,
                    ),
                    "with_default_namespace" => source.with_default_namespace(
                        case.get("uri")
                            .and_then(Value::as_str)
                            .ok_or("namespace URI missing")?,
                    ),
                    _ => return Err("unknown query operation".into()),
                };
                match query {
                    Ok(query) => json!({
                        "query": query,
                        "atom": query.atom(),
                        "result_shape": query.result_shape(),
                        "namespace_bindings": query.namespace_bindings(),
                        "query_bytes": query.query_bytes()?,
                    }),
                    Err(error) => json!({"error": error.to_string()}),
                }
            }
            "policy" => {
                let policy_value = case.get("policy").ok_or("policy missing")?;
                let policy: Policy = if policy_value.is_null() {
                    Policy::default()
                } else {
                    serde_json::from_value(policy_value.clone())?
                };
                let snapshot = PolicySnapshot::from_policy(&policy)?;
                let identity = snapshot.identity();
                json!({"policy": policy, "effective": policy.effective_policy()?,
                    "snapshot": {"policy": snapshot.policy(), "effective_policy": snapshot.effective_policy(),
                        "identity": {"version": identity.version(), "sha256": identity.digest().to_string()}},
                    "max_recording_duration_ms": MAX_RECORDING_DURATION_MS})
            }
            "policy_error" => {
                let policy = Policy {
                    observe: ObservePolicy {
                        enabled: true,
                        native_tab_capture: true,
                        recordings: vec![RecordingRule::default(), RecordingRule::default()],
                        limits: ObserveLimits {
                            max_recordings: 1,
                            ..ObserveLimits::default()
                        },
                        ..ObservePolicy::default()
                    },
                    ..Policy::default()
                };
                match policy.validate() {
                    Err(PolicyError::ObservationRulesExceedRecordingLimit {
                        configured,
                        maximum,
                    }) => json!({"error": {
                        "rust_type": "yosoi_policy::PolicyError",
                        "variant": "ObservationRulesExceedRecordingLimit",
                        "details": {"configured": configured, "maximum": maximum},
                        "source_chain": []
                    }}),
                    Err(error) => return Err(Box::new(error)),
                    Ok(()) => json!({"error": null}),
                }
            }
            "file_document" => {
                let id = case
                    .get("id")
                    .and_then(Value::as_str)
                    .ok_or("file-document identity missing")?;
                let bytes = file_bytes(case.get("bytes").ok_or("file bytes missing")?)?;
                let metadata = file_metadata(case.get("metadata").ok_or("file metadata missing")?)?;
                let maximum_bytes = case
                    .get("max_bytes")
                    .and_then(Value::as_u64)
                    .ok_or("file maximum bytes missing")?;
                let limits = FileLimits::new(maximum_bytes)?;
                let file = file_from_bytes(id.to_owned(), bytes, metadata, limits)?;
                file_value(&file, maximum_bytes)
            }
            "file_limits" => {
                let maximum_bytes = case
                    .get("max_bytes")
                    .and_then(Value::as_u64)
                    .ok_or("file maximum bytes missing")?;
                let limits = FileLimits::new(maximum_bytes)?;
                json!({"max_bytes": limits.max_bytes()})
            }
            "file_too_large_error" => {
                let id = case
                    .get("id")
                    .and_then(Value::as_str)
                    .ok_or("file-document identity missing")?;
                let bytes = file_bytes(case.get("bytes").ok_or("file bytes missing")?)?;
                let maximum_bytes = case
                    .get("max_bytes")
                    .and_then(Value::as_u64)
                    .ok_or("file maximum bytes missing")?;
                let metadata = FileMetadata::new();
                let limits = FileLimits::new(maximum_bytes)?;
                match file_from_bytes(id.to_owned(), bytes, metadata, limits) {
                    Err(FileDocumentError::TooLarge { maximum, observed }) => json!({
                        "error": {
                            "rust_type": "yosoi::documents::FileDocumentError",
                            "variant": "TooLarge",
                            "details": {"maximum": maximum, "observed": observed},
                            "source_chain": []
                        }
                    }),
                    Err(error) => return Err(Box::new(error)),
                    Ok(_) => json!({"error": null}),
                }
            }
            "typed_file_document" => {
                let id = case
                    .get("id")
                    .and_then(Value::as_str)
                    .ok_or("file-document identity missing")?;
                let family = case
                    .get("family")
                    .and_then(Value::as_str)
                    .ok_or("file-document family missing")?;
                let constructor = case
                    .get("constructor")
                    .and_then(Value::as_str)
                    .ok_or("file-document constructor missing")?;
                let bytes = file_bytes(case.get("bytes").ok_or("file bytes missing")?)?;
                let metadata = file_metadata(case.get("metadata").ok_or("file metadata missing")?)?;
                let maximum_bytes = case
                    .get("max_bytes")
                    .and_then(Value::as_u64)
                    .ok_or("file maximum bytes missing")?;
                let file = typed_file_document(
                    family,
                    constructor,
                    id.to_owned(),
                    bytes,
                    metadata,
                    maximum_bytes,
                )?;
                let retained_limit = if constructor == "default" {
                    DEFAULT_FILE_MAX_BYTES
                } else {
                    maximum_bytes
                };
                file_value(&file, retained_limit)
            }
            "file_metadata_error" => {
                let filename = case
                    .get("filename")
                    .and_then(Value::as_str)
                    .ok_or("metadata filename missing")?;
                match FileMetadata::new().with_filename(filename.to_owned()) {
                    Err(FileDocumentError::MetadataTooLong {
                        field,
                        maximum,
                        observed,
                    }) => json!({"error": {
                        "rust_type": "yosoi::documents::FileDocumentError",
                        "variant": "MetadataTooLong",
                        "details": {"field": field, "maximum": maximum, "observed": observed},
                        "source_chain": []
                    }}),
                    Err(error) => return Err(Box::new(error)),
                    Ok(_) => json!({"error": null}),
                }
            }
            "document" | "contract" => {
                let profile: DocumentProfile = serde_json::from_value(
                    case.get("profile")
                        .ok_or("document profile missing")?
                        .clone(),
                )?;
                let id = DocumentId::try_new(name)?;
                let content = case
                    .get("content")
                    .and_then(Value::as_str)
                    .ok_or("case content missing")?;
                let document = Document::from_profile(id, profile, content.as_bytes())?;
                let plan: Plan = serde_json::from_value(
                    case.get("plan").ok_or("document plan missing")?.clone(),
                )?;
                let located = document.locate(&plan);
                if kind == "contract" {
                    let schema: ContractSchema = serde_json::from_value(
                        case.get("schema").ok_or("contract schema missing")?.clone(),
                    )?;
                    let contract = RuntimeContract::new(schema)?;
                    let extracted = contract.extract(&located);
                    let outcome = extracted.clone().validate();
                    let archived = outcome.to_archived(contract.schema())?;
                    let typed_values = match &outcome {
                        RuntimeContractOutcome::Evaluated { records, .. } => records
                            .iter()
                            .map(|record| {
                                let mut object = serde_json::Map::new();
                                for (field, value) in &record.value {
                                    object.insert(
                                        field.as_str().to_owned(),
                                        match value {
                                            RuntimeFieldValue::ExactlyOne { value } => {
                                                scalar(value)
                                            }
                                            RuntimeFieldValue::ZeroOrOne { value } => {
                                                value.as_ref().map_or(Value::Null, scalar)
                                            }
                                            RuntimeFieldValue::Many { values } => {
                                                Value::Array(values.iter().map(scalar).collect())
                                            }
                                        },
                                    );
                                }
                                Value::Object(object)
                            })
                            .collect::<Vec<_>>(),
                        _ => Vec::new(),
                    };
                    let required_wire = match outcome.clone().require_all() {
                        Ok(records) => json!({"records": records}),
                        Err(error) => json!({"error": error}),
                    };
                    // Python's documented typed candidate view includes every
                    // schema field, even when the original wire omits empty ones.
                    // Compare that view and the untouched Rust wire separately.
                    let mut required = required_wire.clone();
                    if let Some(records) = required.get_mut("records").and_then(Value::as_array_mut)
                    {
                        for record in records {
                            let fields = record
                                .get_mut("candidate")
                                .and_then(|candidate| candidate.get_mut("fields"))
                                .and_then(Value::as_object_mut)
                                .ok_or("required record is missing candidate fields")?;
                            for field in contract.schema().fields() {
                                fields
                                    .entry(field.id().as_str())
                                    .or_insert_with(|| json!([]));
                            }
                        }
                    }
                    json!({"profile": profile, "class": document.class(), "byte_len": document.byte_len(),
                        "plan": plan, "located": located, "identity": contract.schema().identity()?.to_string(),
                        "extracted": extracted, "outcome": outcome, "archived": archived, "required": required, "required_wire": required_wire, "typed_values": typed_values})
                } else {
                    json!({"profile": profile, "class": document.class(), "byte_len": document.byte_len(),
                        "plan": plan, "located": located})
                }
            }
            _ => return Err("unknown conformance case kind".into()),
        };
        results.push(json!({"name": name, "result": result}));
    }
    println!("{}", serde_json::to_string(&results)?);
    Ok(())
}

fn default_json<T: Default + serde::Serialize>() -> Result<Value, Box<dyn Error>> {
    Ok(serde_json::to_value(T::default())?)
}

fn default_model(type_name: &str) -> Result<Value, Box<dyn Error>> {
    use yosoi::policy as p;
    match type_name {
        "yosoi::Policy" => default_json::<p::Policy>(),
        "yosoi::policy::Page" => default_json::<p::Page>(),
        "yosoi::policy::Request" => default_json::<p::Request>(),
        "yosoi::policy::SourceLimits" => default_json::<p::SourceLimits>(),
        "yosoi::policy::BrowserLimits" => default_json::<p::BrowserLimits>(),
        "yosoi::policy::DirectHttpRedirects" => default_json::<p::DirectHttpRedirects>(),
        "yosoi::policy::Documents" => default_json::<p::Documents>(),
        "yosoi::policy::Locators" => default_json::<p::Locators>(),
        "yosoi::policy::Map" => default_json::<p::Map>(),
        "yosoi::policy::Limits" => default_json::<p::Limits>(),
        "yosoi::policy::Filters" => default_json::<p::Filters>(),
        "yosoi::policy::Scope" => default_json::<p::Scope>(),
        "yosoi::policy::Tuning" => default_json::<p::Tuning>(),
        "yosoi::policy::search::Search" => default_json::<p::search::Search>(),
        "yosoi::policy::EventLimit" => default_json::<p::EventLimit>(),
        "yosoi::policy::MaximumElapsed" => default_json::<p::MaximumElapsed>(),
        "yosoi::policy::RedirectHopLimit" => default_json::<p::RedirectHopLimit>(),
        "yosoi::policy::ObserveLimits" => default_json::<p::ObserveLimits>(),
        "yosoi::policy::ObservePolicy" => default_json::<p::ObservePolicy>(),
        "yosoi::policy::RecordingRule" => default_json::<p::RecordingRule>(),
        "yosoi::policy::ScreenshotPolicy" => default_json::<p::ScreenshotPolicy>(),
        "yosoi::documents::FileLimits" => default_json::<FileLimits>(),
        "yosoi::documents::FileMetadata" => default_json::<FileMetadata>(),
        "yosoi::map::Summary" => default_json::<Summary>(),
        "yosoi::search::SearchHitMetadata" => default_json::<SearchHitMetadata>(),
        _ => Err("unsupported default model".into()),
    }
}

fn scalar(value: &RuntimeValue) -> Value {
    match value {
        RuntimeValue::String(value) => json!(value),
    }
}
