//! Snapshot helpers for the executable image conformance fixture.

use serde_json::{Map, Value, json};
use std::{error::Error, io};
use yosoi::surface::{ImageSurface, PixelArtifact, SurfaceError, model::SurfaceRead};

pub fn artifact(value: &PixelArtifact) -> Result<Value, Box<dyn Error>> {
    let pixels = image::load_from_memory(value.bytes())?.to_rgba8();
    Ok(
        json!({"class": "PixelArtifact", "info": value.info(), "bytes": value.bytes(),
        "document_id": value.document().id(), "metadata": value.document().metadata(),
        "rgba": pixels.as_raw(), "width": pixels.width(), "height": pixels.height()}),
    )
}

pub fn reader(value: &ImageSurface) -> Result<Value, Box<dyn Error>> {
    Ok(
        json!({"class": "ImageSurface", "descriptor": value.descriptor(),
        "observation": value.observation(), "root": value.root_reference(),
        "source_artifact": artifact(value.source_artifact())?}),
    )
}

pub fn case(name: &str, method: &str, arguments: Value, value: Value) -> Value {
    let path = if method.starts_with("SurfaceRead::") {
        format!("yosoi::surface::model::{method}")
    } else {
        format!("yosoi::surface::{method}")
    };
    Value::Object(Map::from_iter([
        ("name".to_owned(), Value::String(name.to_owned())),
        ("rustPath".to_owned(), Value::String(path)),
        ("input".to_owned(), arguments),
        ("rust".to_owned(), value),
    ]))
}

pub fn error(
    name: &str,
    method: &str,
    arguments: Value,
    result: Result<(), SurfaceError>,
) -> Result<Value, Box<dyn Error>> {
    let failure = match result {
        Ok(()) => return Err(io::Error::other(format!("{name} unexpectedly succeeded")).into()),
        Err(error) => error,
    };
    let (variant, details) = match &failure {
        SurfaceError::Invalid(message) => ("Invalid", json!({"message": message})),
        SurfaceError::Parse(message) => ("Parse", json!({"message": message})),
        SurfaceError::Limit(limit) => ("Limit", json!({"limit": limit})),
        SurfaceError::WrongCapture => ("WrongCapture", json!({})),
        _ => return Err(io::Error::other(format!("unhandled image error: {failure}")).into()),
    };
    Ok(case(
        name,
        method,
        arguments,
        json!({"rust_type": "yosoi::surface::SurfaceError", "variant": variant, "details": details, "source_chain": []}),
    ))
}
