//! One bounded, binary-safe Document frame for Request-to-Locate pipes.

use std::io::{Read, Write};

use anyhow::{Context as _, Result, bail};
use serde::{Deserialize, Serialize};
use yosoi_engine::{Document, DocumentId, DocumentProfile};

const MAGIC: &[u8; 8] = b"YSOIDOC1";
const FORMAT_VERSION: u32 = 1;
const MAX_HEADER_BYTES: usize = 8_192;
const MAX_PAYLOAD_BYTES: usize = 67_108_864;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Header {
    format_version: u32,
    document_id: DocumentId,
    profile: DocumentProfile,
    byte_len: u64,
}

pub fn write_to(writer: &mut impl Write, document: &Document) -> Result<()> {
    let payload = document.bytes();
    if payload.len() > MAX_PAYLOAD_BYTES {
        bail!("Document exceeds the {MAX_PAYLOAD_BYTES} byte CLI pipe limit");
    }
    let header = Header {
        format_version: FORMAT_VERSION,
        document_id: document.id().clone(),
        profile: document.profile(),
        byte_len: document.byte_len(),
    };
    let header_bytes = serde_json::to_vec(&header).context("could not encode Document header")?;
    if header_bytes.len() > MAX_HEADER_BYTES {
        bail!("Document header exceeds the {MAX_HEADER_BYTES} byte CLI pipe limit");
    }
    let header_length =
        u32::try_from(header_bytes.len()).context("Document header is too large")?;
    writer
        .write_all(MAGIC)
        .context("could not write Document pipe magic")?;
    writer
        .write_all(&header_length.to_be_bytes())
        .context("could not write Document header length")?;
    writer
        .write_all(&header_bytes)
        .context("could not write Document header")?;
    writer
        .write_all(payload)
        .context("could not write Document bytes")?;
    Ok(())
}

pub fn read_from(reader: &mut impl Read) -> Result<Document> {
    let mut magic = [0_u8; 8];
    reader
        .read_exact(&mut magic)
        .context("Document pipe is missing its magic")?;
    if &magic != MAGIC {
        bail!("input is not a Yosoi Document pipe frame");
    }
    let mut length_bytes = [0_u8; 4];
    reader
        .read_exact(&mut length_bytes)
        .context("Document pipe header length is truncated")?;
    let header_length = usize::try_from(u32::from_be_bytes(length_bytes))
        .context("Document header length is not addressable")?;
    if header_length == 0 || header_length > MAX_HEADER_BYTES {
        bail!("Document pipe header length is outside the supported limit");
    }
    let mut header_bytes = vec![0_u8; header_length];
    reader
        .read_exact(&mut header_bytes)
        .context("Document pipe header is truncated")?;
    let header: Header =
        serde_json::from_slice(&header_bytes).context("invalid Document pipe header")?;
    if header.format_version != FORMAT_VERSION {
        bail!(
            "unsupported Document pipe format version {}",
            header.format_version
        );
    }
    let payload_length =
        usize::try_from(header.byte_len).context("Document pipe byte length is not addressable")?;
    if payload_length > MAX_PAYLOAD_BYTES {
        bail!("Document pipe payload exceeds the {MAX_PAYLOAD_BYTES} byte limit");
    }
    let mut payload = vec![0_u8; payload_length];
    reader
        .read_exact(&mut payload)
        .context("Document pipe payload is truncated")?;
    let mut extra = [0_u8; 1];
    if reader
        .read(&mut extra)
        .context("could not finish reading Document pipe")?
        != 0
    {
        bail!("Document pipe contains trailing bytes after its one frame");
    }
    Document::from_profile(header.document_id, header.profile, payload)
        .context("Document pipe has invalid public Document data")
}

#[cfg(test)]
mod tests {
    #![allow(clippy::panic_in_result_fn)] // Assertions intentionally fail frame tests.

    use std::error::Error;
    use std::io::Cursor;

    use yosoi_engine::{Document, prelude::DocumentEpoch};

    use super::{read_from, write_to};

    #[test]
    fn preserves_rendered_dom_profile_epoch_and_bytes() -> Result<(), Box<dyn Error>> {
        let epoch = DocumentEpoch::try_from(42)?;
        let original = Document::rendered_dom("browser-doc", epoch, b"{\"node\":1}".to_vec())?;
        let mut frame = Vec::new();
        write_to(&mut frame, &original)?;
        let restored = read_from(&mut Cursor::new(frame))?;
        assert_eq!(restored.id(), original.id());
        assert_eq!(restored.profile(), original.profile());
        assert_eq!(restored.bytes(), original.bytes());
        Ok(())
    }

    #[test]
    fn rejects_trailing_bytes_after_one_document() -> Result<(), Box<dyn Error>> {
        let original = Document::text("text", b"hello".to_vec())?;
        let mut frame = Vec::new();
        write_to(&mut frame, &original)?;
        frame.push(0);
        assert!(read_from(&mut Cursor::new(frame)).is_err());
        Ok(())
    }
}
