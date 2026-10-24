use super::{VideoError, VideoSurface};
use crate::surface::{
    PixelRect, SurfaceError,
    model::{
        self, AddressToken, ContinuationToken, ReadOperation, ReadRequest, ReadResult, SurfaceRead,
    },
};
use serde::{Deserialize, Serialize};
use serde_json::json;
#[derive(Debug)]
pub(super) enum Address {
    Interval(u64, u64),
    Frame(u64),
    Region(u64, PixelRect),
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Cursor {
    observation: String,
    operation: String,
    offset: usize,
}
impl VideoSurface {
    pub(super) fn address(&self, reference: &model::Reference) -> Result<Address, VideoError> {
        if reference.observation != self.data.observation.id {
            return Err(SurfaceError::WrongCapture.into());
        }
        let parts = reference.address.as_str().split(':').collect::<Vec<_>>();
        let parse = |i: usize| -> Result<u64, VideoError> {
            parts
                .get(i)
                .ok_or_else(|| VideoError::Invalid("missing video address component".into()))?
                .parse()
                .map_err(|_| VideoError::Invalid("invalid video address component".into()))
        };
        let address = match parts.first().copied() {
            Some("t") if parts.len() == 3 => {
                let start = parse(1)?;
                let end = parse(2)?;
                if start >= end || end > self.data.metadata.duration_us {
                    return Err(VideoError::Invalid("interval is outside the video".into()));
                }
                Address::Interval(start, end)
            }
            Some("f") if parts.len() == 2 => {
                let time = parse(1)?;
                self.at(time)?;
                Address::Frame(time)
            }
            Some("r") if parts.len() == 6 => {
                let time = parse(1)?;
                self.at(time)?;
                let rect = PixelRect {
                    x: u32::try_from(parse(2)?)
                        .map_err(|_| VideoError::Invalid("crop coordinate overflow".into()))?,
                    y: u32::try_from(parse(3)?)
                        .map_err(|_| VideoError::Invalid("crop coordinate overflow".into()))?,
                    width: u32::try_from(parse(4)?)
                        .map_err(|_| VideoError::Invalid("crop coordinate overflow".into()))?,
                    height: u32::try_from(parse(5)?)
                        .map_err(|_| VideoError::Invalid("crop coordinate overflow".into()))?,
                };
                if rect.width == 0 || rect.height == 0 {
                    return Err(VideoError::Invalid("empty crop".into()));
                }
                Address::Region(time, rect)
            }
            _ => return Err(VideoError::Invalid("unknown video address".into())),
        };
        Ok(address)
    }
    fn continuation(
        &self,
        request: &ReadRequest,
        offset: usize,
    ) -> Result<ContinuationToken, SurfaceError> {
        let cursor = Cursor {
            observation: self.data.observation.id.as_str().into(),
            operation: serde_json::to_string(&request.operation)
                .map_err(|e| SurfaceError::Parse(e.to_string()))?,
            offset,
        };
        ContinuationToken::new(
            serde_json::to_string(&cursor).map_err(|e| SurfaceError::Parse(e.to_string()))?,
        )
    }
    fn offset(&self, request: &ReadRequest) -> Result<usize, SurfaceError> {
        let Some(token) = &request.continuation else {
            return Ok(0);
        };
        let cursor: Cursor = serde_json::from_str(token.as_str())
            .map_err(|error| SurfaceError::Invalid(error.to_string()))?;
        if cursor.observation != self.data.observation.id.as_str()
            || cursor.operation
                != serde_json::to_string(&request.operation)
                    .map_err(|e| SurfaceError::Parse(e.to_string()))?
        {
            return Err(SurfaceError::Invalid(
                "continuation belongs to another observation, operation or scope".into(),
            ));
        }
        Ok(cursor.offset)
    }
    fn reference_at(&self, address: String) -> Result<model::Reference, SurfaceError> {
        Ok(model::Reference {
            observation: self.data.observation.id.clone(),
            address: AddressToken::new(address)?,
        })
    }
    fn entries(&self, start: u64, end: u64) -> Result<Vec<model::Entry>, SurfaceError> {
        let length = end
            .checked_sub(start)
            .ok_or_else(|| SurfaceError::Invalid("invalid interval".into()))?;
        if length <= self.data.policy.min_interval_us {
            let position = start
                .checked_add(length.checked_div(2).unwrap_or_default())
                .ok_or(SurfaceError::Limit("timeline arithmetic"))?;
            return Ok(vec![model::Entry {
                reference: self.reference_at(format!("f:{position}"))?,
                kind: "frame_request".into(),
                label: format!("Frame near {position} us"),
                preview: "Invoke video.frame@1 to request pixel evidence at this position".into(),
                members: None,
            }]);
        }
        let divisions = length.min(8);
        let mut entries = Vec::new();
        for i in 0..divisions {
            let bound = |i: u64| {
                length
                    .checked_mul(i)
                    .and_then(|v| v.checked_div(divisions))
                    .and_then(|v| start.checked_add(v))
                    .ok_or(SurfaceError::Limit("timeline arithmetic"))
            };
            let left = bound(i)?;
            let right = bound(
                i.checked_add(1)
                    .ok_or(SurfaceError::Limit("timeline arithmetic"))?,
            )?;
            entries.push(model::Entry {
                reference: self.reference_at(format!("t:{left}:{right}"))?,
                kind: "interval".into(),
                label: format!("{left}..{right} us"),
                preview: "Temporal extent only; expanding does not imply that frames were observed"
                    .into(),
                members: Some(
                    if right.saturating_sub(left) <= self.data.policy.min_interval_us {
                        1
                    } else {
                        8
                    },
                ),
            });
        }
        Ok(entries)
    }
    fn read_inner(&self, request: &ReadRequest) -> Result<ReadResult, SurfaceError> {
        if !(512..=65536).contains(&request.budget.bytes) {
            return Err(SurfaceError::Invalid(
                "read budget must be 512..65536 bytes".into(),
            ));
        }
        let offset = self.offset(request)?;
        match &request.operation {
            ReadOperation::Inspect { reference } => {
                let address = self
                    .address(reference)
                    .map_err(|e| SurfaceError::Invalid(e.to_string()))?;
                let detail = match address {
                    Address::Interval(start, end) => {
                        json!({"kind":"interval","start_us":start,"end_us":end,"metadata":self.data.metadata,"pixel_evidence_in_response":false})
                    }
                    Address::Frame(time) => {
                        json!({"kind":"frame_request","requested_position_us":time,"pixel_space":"decoded_frame","capability":"video.frame@1","frame_pixels_observed":false})
                    }
                    Address::Region(time, rect) => {
                        json!({"kind":"crop_request","requested_position_us":time,"region":rect,"pixel_space":"decoded_full_frame","capability":"video.frame@1","frame_pixels_observed":false})
                    }
                };
                let content = serde_json::to_string(&detail)
                    .map_err(|e| SurfaceError::Parse(e.to_string()))?;
                let rest = content
                    .get(offset..)
                    .ok_or_else(|| SurfaceError::Invalid("invalid inspection offset".into()))?;
                let mut part = rest.chars().take(request.budget.bytes).collect::<String>();
                loop {
                    if part.is_empty() && !rest.is_empty() {
                        return Err(SurfaceError::BudgetTooSmall);
                    }
                    let end = offset
                        .checked_add(part.len())
                        .ok_or(SurfaceError::Limit("inspection offset"))?;
                    let result = ReadResult::Inspection(model::Inspection {
                        reference: reference.clone(),
                        media_type: "application/vnd.yosoi.video-evidence.v1+json".into(),
                        total_bytes: content.len(),
                        offset,
                        content: part.clone(),
                        next: if end < content.len() {
                            Some(self.continuation(request, end)?)
                        } else {
                            None
                        },
                        coverage: self.data.observation.coverage.clone(),
                    });
                    if serde_json::to_vec(&result)
                        .map_err(|e| SurfaceError::Parse(e.to_string()))?
                        .len()
                        <= request.budget.bytes
                    {
                        return Ok(result);
                    }
                    part.pop();
                }
            }
            ReadOperation::Overview | ReadOperation::Expand { .. } => {
                let (start, end) = match &request.operation {
                    ReadOperation::Overview => (0, self.data.metadata.duration_us),
                    ReadOperation::Expand { reference } => match self
                        .address(reference)
                        .map_err(|e| SurfaceError::Invalid(e.to_string()))?
                    {
                        Address::Interval(start, end) => (start, end),
                        _ => {
                            return Err(SurfaceError::Invalid(
                                "frame addresses materialize pixels; only intervals subdivide"
                                    .into(),
                            ));
                        }
                    },
                    _ => return Err(SurfaceError::Invalid("unsupported read".into())),
                };
                let entries = self.entries(start, end)?;
                if offset > entries.len() {
                    return Err(SurfaceError::Invalid(
                        "continuation offset outside population".into(),
                    ));
                }
                let mut count = request
                    .budget
                    .items
                    .clamp(1, 100)
                    .min(entries.len().saturating_sub(offset));
                loop {
                    let end = offset
                        .checked_add(count)
                        .ok_or(SurfaceError::Limit("page offset"))?;
                    let page = model::Page {
                        observation: self.data.observation.id.clone(),
                        total: entries.len(),
                        offset,
                        entries: entries.iter().skip(offset).take(count).cloned().collect(),
                        next: if end < entries.len() {
                            Some(self.continuation(request, end)?)
                        } else {
                            None
                        },
                        coverage: self.data.observation.coverage.clone(),
                    };
                    let result = ReadResult::Page(page);
                    if serde_json::to_vec(&result)
                        .map_err(|e| SurfaceError::Parse(e.to_string()))?
                        .len()
                        <= request.budget.bytes
                    {
                        return Ok(result);
                    }
                    if count <= 1 {
                        return Err(SurfaceError::BudgetTooSmall);
                    }
                    count = count.saturating_sub(1);
                }
            }
            ReadOperation::Search { .. } => Err(SurfaceError::Invalid(
                "video does not advertise text search: no OCR or transcription was performed"
                    .into(),
            )),
            ReadOperation::Parent { .. } => Err(SurfaceError::Invalid(
                "video does not advertise a universal parent relation".into(),
            )),
        }
    }
}
impl SurfaceRead for VideoSurface {
    fn descriptor(&self) -> &model::Descriptor {
        &self.data.descriptor
    }
    fn observation(&self) -> &model::Observation {
        &self.data.observation
    }
    fn root_reference(&self) -> model::Reference {
        self.data.root.clone()
    }
    fn read(&self, request: &ReadRequest) -> Result<ReadResult, SurfaceError> {
        self.read_inner(request)
    }
}
