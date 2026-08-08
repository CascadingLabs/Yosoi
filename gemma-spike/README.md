# Gemma 4 inference spike

CAS-268 harness for a single vLLM worker on Echo, reached from a laptop over Tailscale.

## Echo deployment

```bash
cd gemma-spike
cp .env.example .env
# Set HF_TOKEN and deployment values in .env; do not commit .env.
docker compose up -d
watch docker compose ps
```

Set `VLLM_BIND_ADDRESS` to Echo's numeric Tailscale IPv4. Compose exposes `8096` on that address and an Echo-only control endpoint on `127.0.0.1:8097` for network-overhead comparisons. Do not use Funnel or publish the port through a public reverse proxy. Restrict access with the Echo host firewall/Tailscale ACLs.

The default selects GPU 1, one worker, normal KV caching, and prefix caching. `GPU_DEVICE=0` selects the other card. Verify the installed vLLM image supports the Gemma 4 checkpoint and multimodal flags before a long model download.

## Laptop smoke test

```bash
export INFERENCE_BASE_URL=http://echo:8096/v1
uv run python scripts/smoke_test.py --image /path/to/frozen-screenshot.png
```

## Microbench

```bash
uv run python scripts/bench_inference.py \
  --image /path/to/frozen-screenshot.png \
  --runs 5 \
  --output results/gemma4.jsonl
```

Each JSONL row records model, endpoint, input/vision tokens when vLLM exposes them, image dimensions, cold/warm label, TTFT, wall latency, output tokens, decode tok/s, raw usage, and nullable prefill fields. The client intentionally targets the Tailscale URL rather than localhost. Use `--base-url http://127.0.0.1:8096/v1` only for an explicit network-overhead comparison.

Summarize artifacts:

```bash
uv run python scripts/summarize_results.py results/*.jsonl
```

The first request is cold-labelled, not guaranteed cold. Restart vLLM for a true cold-cache run. This microbench does not establish correctness or VRAM; combine it with boss-fight results and Echo `nvidia-smi` snapshots.

## Static HTML structured-output spike

Run one bounded static Wikipedia case through Pydantic AI's native JSON-schema output:

```bash
export INFERENCE_BASE_URL=http://echo:8096/v1
export INFERENCE_API_KEY=EMPTY
uv run python scripts/static_html_boss_fight.py \
  --url https://en.wikipedia.org/wiki/Web_scraping
```

The harness keeps only the article title and first three paragraphs (one pruning pass), then requests a `WikipediaAnswer` object. It uses OpenAI-compatible `response_format`/JSON Schema rather than tool output. The successful result is saved to `results/wikipedia-static-structured.json`.

No additional server-side grammar flag was required with the deployed vLLM image: native JSON Schema completed successfully. `--enable-auto-tool-choice --tool-call-parser gemma4` remains required for Yosoi's tool-based selector discovery, but is not the structured-output mechanism used by this harness. K3s is intentionally not part of this spike.
