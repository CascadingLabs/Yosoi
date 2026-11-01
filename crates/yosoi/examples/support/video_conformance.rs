//! Actual decoded video evidence snapshots, with no generated pass rows.

use serde_json::{Map, Value, json};
use std::{error::Error, io};
use yosoi::surface::{
    SurfaceError,
    model::SurfaceRead,
    video::{DecodedFrame, VideoError, VideoSurface},
};

pub fn video(value: &VideoSurface) -> Value {
    json!({"class":"VideoSurface","descriptor":value.descriptor(),"observation":value.observation(),"root":value.root_reference(),"metadata":value.metadata(),"policy":value.policy(),"source_document":value.source_document().map(|document|json!({"class":"VideoDocument","id":document.id(),"bytes":document.bytes(),"metadata":document.metadata(),"sha256":document.sha256(),"byte_len":document.byte_len()}))})
}

pub fn frame(value: &DecodedFrame) -> Result<Value, Box<dyn Error>> {
    let pixels = image::load_from_memory(&value.png)?.to_rgba8();
    let artifact = value.pixel_artifact()?;
    Ok(
        json!({"class":"DecodedFrame","info":value.info,"png":value.png,"rgba":pixels.as_raw(),"pixel_artifact":artifact.as_ref().map(|artifact|json!({"info":artifact.info(),"bytes":artifact.bytes()}))}),
    )
}

pub fn case(name: &str, path: &str, arguments: Value, value: Value) -> Value {
    Value::Object(Map::from_iter([
        ("name".to_owned(), json!(name)),
        ("rustPath".to_owned(), json!(path)),
        ("input".to_owned(), arguments),
        ("rust".to_owned(), value),
    ]))
}

pub fn error(
    name: &str,
    path: &str,
    arguments: Value,
    expected: &str,
    result: Result<(), VideoError>,
) -> Result<Value, Box<dyn Error>> {
    let Err(failure) = result else {
        return Err(io::Error::other(format!("{name} unexpectedly succeeded")).into());
    };
    let (variant, details) = match &failure {
        VideoError::Cancelled => ("Cancelled", json!({})),
        VideoError::NoFrameAtOrAfter { requested_us } => {
            ("NoFrameAtOrAfter", json!({"requested_us":requested_us}))
        }
        VideoError::Invalid(message) => ("Invalid", json!({"message":message})),
        VideoError::Surface(SurfaceError::WrongCapture) => (
            "Surface",
            json!({"surface":{"variant":"WrongCapture","details":{}}}),
        ),
        other => {
            return Err(io::Error::other(format!("unexpected {name} failure: {other}")).into());
        }
    };
    if variant != expected {
        return Err(
            io::Error::other(format!("{name} returned {variant}, expected {expected}")).into(),
        );
    }
    let mut chain = Vec::new();
    let mut source = failure.source();
    while let Some(error) = source {
        chain.push(error.to_string());
        source = error.source();
    }
    Ok(case(
        name,
        path,
        arguments,
        json!({"rust_type":"yosoi::surface::video::VideoError","variant":variant,"details":details,"source_chain":chain}),
    ))
}
