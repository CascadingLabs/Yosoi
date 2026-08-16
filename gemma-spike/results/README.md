JSONL benchmark artifacts belong here and should stay out of source control unless intentionally attached to the CAS-268 result.

Each row records the remote endpoint, model, image dimensions, cache-state label, TTFT, wall latency, output tokens, decode tok/s, raw usage, and nullable vision/prefill fields. `summarize_results.py` produces p50/p95 summaries.

Interpretation note: the first request is only *cold-labelled*; restart vLLM or clear the prefix-cache state for a true cold run. `vision_tokens`, `prefill_tps`, and VRAM are nullable because the OpenAI streaming response does not reliably expose them; collect Echo `nvidia-smi` snapshots separately.
