use std::str;

use encoding_rs::{DecoderResult, Encoding};

use super::decode::DecodingErrorCode;

pub(super) struct Decoded {
    pub(super) text: String,
    pub(super) replacements: u64,
    pub(super) output_truncated: bool,
    pub(super) incomplete: bool,
}

pub(super) fn bounded_decode(
    input: &[u8],
    encoding: &'static Encoding,
    limit: u64,
    strict: bool,
    source_truncated: bool,
) -> Result<Decoded, DecodingErrorCode> {
    let maximum = usize::try_from(limit).unwrap_or(usize::MAX);
    let mut decoder = encoding.new_decoder_without_bom_handling();
    let mut output = String::with_capacity(maximum.min(8192));
    let mut at = 0;
    let mut replacements = 0_u64;
    let mut incomplete = false;
    let mut truncated = false;
    let mut finishing = false;
    loop {
        let remaining = maximum.saturating_sub(output.len());
        let capacity = remaining.saturating_add(4).clamp(4, 8192);
        let mut buffer = vec![0_u8; capacity];
        // Feeding with `last = false` makes encoding_rs retain a potentially
        // incomplete terminal sequence.  Only the subsequent empty, final
        // call can classify that state as terminal incompleteness.  Malformed
        // results while input is still being fed are definitive invalid data.
        let decoder_input = if finishing {
            &[][..]
        } else {
            input.get(at..).unwrap_or_default()
        };
        let (result, read, written) =
            decoder.decode_to_utf8_without_replacement(decoder_input, &mut buffer, finishing);
        at = at.saturating_add(read);
        let valid = str::from_utf8(buffer.get(..written).unwrap_or_default())
            .map_err(|_| DecodingErrorCode::InvalidSequence)?;
        append_bounded(&mut output, valid, maximum, &mut truncated);
        match result {
            DecoderResult::InputEmpty if !finishing => {
                finishing = true;
            }
            DecoderResult::InputEmpty => break,
            DecoderResult::OutputFull if remaining == 0 => {
                truncated = true;
                break;
            }
            DecoderResult::OutputFull => {}
            DecoderResult::Malformed(_, _) if finishing && source_truncated => {
                incomplete = true;
                break;
            }
            DecoderResult::Malformed(_, _) if strict => {
                return Err(DecodingErrorCode::InvalidSequence);
            }
            DecoderResult::Malformed(_, _) => {
                replacements = replacements.saturating_add(1);
                append_bounded(&mut output, "�", maximum, &mut truncated);
            }
        }
        if truncated {
            break;
        }
    }
    Ok(Decoded {
        text: output,
        replacements,
        output_truncated: truncated,
        incomplete,
    })
}

#[cfg(test)]
#[path = "decode_stream_tests.rs"]
mod tests;

fn append_bounded(output: &mut String, value: &str, maximum: usize, truncated: &mut bool) {
    for character in value.chars() {
        if output.len().saturating_add(character.len_utf8()) > maximum {
            *truncated = true;
            return;
        }
        output.push(character);
    }
}
