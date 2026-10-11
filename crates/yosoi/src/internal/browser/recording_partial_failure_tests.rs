use super::*;

fn canvas(width: u32, height: u32) -> RgbaImage {
    RgbaImage::from_pixel(width, height, Rgba([255, 255, 255, 255]))
}

#[tokio::test]
#[allow(clippy::unwrap_used, reason = "test")]
async fn partial_frame_failure_preserves_retained_frames_and_honest_facts() {
    let mut bytes = Cursor::new(Vec::new());
    DynamicImage::ImageRgba8(canvas(10, 8))
        .write_to(&mut bytes, ImageFormat::Png)
        .unwrap();
    let collected = CollectedFrames {
        frames: vec![RawFrame {
            offset: Duration::ZERO,
            data: bytes.into_inner(),
            masks: Vec::new(),
            device_width: 10.0,
            device_height: 8.0,
        }],
        dropped_by_rate: 2,
        dropped_by_limit: 3,
        dropped_by_listener: 0,
        decode_failures: 1,
        ack_failures: 0,
        stream_disconnected: false,
    };

    let recording = build_regions(
        collected,
        &[("viewport".into(), None)],
        Vec::new(),
        &RecordingOptions::default(),
        Duration::from_secs(1),
        1.0,
        false,
        Some(1),
        DocumentEpoch::Known(1),
    )
    .await
    .unwrap();

    assert_eq!(recording.frames_captured, 1);
    assert_eq!(recording.regions[0].frames.len(), 1);
    assert_eq!(recording.frames_dropped, 6);
    assert!(!recording.complete);
    assert_eq!(recording.frame_size_pixels, Some((10, 8)));
    assert_eq!(recording.capture_viewport_css, Some((10.0, 8.0)));
}
