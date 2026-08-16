# Echo deployment runbook

This deploys the CAS-268 spike as one vLLM worker on Echo. The client remains on the laptop and reaches Echo through Tailscale. No Funnel, public proxy, or K3s is required.

## 1. Verify Echo prerequisites

Run on Echo:

```bash
nvidia-smi
nvidia-smi --query-gpu=index,name,memory.total --format=csv
docker --version
docker compose version
docker info --format '{{json .Runtimes}}'
tailscale ip -4
```

`docker compose` must report Compose v2. The legacy `docker-compose` 1.29.x command is not compatible with Python 3.12 and is not supported by this runbook. If `docker compose version` says `unknown command`, install the Compose v2 plugin:

```bash
# Ubuntu/Debian with Docker's official repository configured:
sudo apt-get update
sudo apt-get install -y docker-compose-plugin

# Debian/Ubuntu distro package alternative:
# sudo apt-get install -y docker-compose-v2

docker compose version
```

If neither package exists, configure Docker's official apt repository first; do not install the legacy Python `docker-compose` package. Confirm the NVIDIA Container Toolkit is installed and GPU `1` is the intended card. Do not continue if Docker cannot see NVIDIA GPUs.

## 2. Copy the spike to Echo

From the laptop, copy the workspace contents using your normal approved transfer method. For example:

```bash
rsync -az --exclude '.env' --exclude 'results/*.jsonl' \
  /home/andrew/Desktop/cl/cas-268-gemma-spike--Yosoi/gemma-spike/ \
  echo:~/yosoi/gemma-spike/
```

Do not copy credentials into the repository or commit `.env`.

## 3. Configure Echo

On Echo:

```bash
cd ~/yosoi/gemma-spike
cp .env.example .env
chmod 600 .env
${EDITOR:-vi} .env
```

Set at least:

```dotenv
HF_TOKEN=<read-only Hugging Face token with Gemma access>
GPU_DEVICE=1
MODEL_ID=google/gemma-4-12b-it
VLLM_BIND_ADDRESS=<Echo's Tailscale IPv4 from `tailscale ip -4`>
VLLM_PORT=8096
```

For the QAT comparison, stop the service, change only `MODEL_ID`, and start it again with a separate results file:

```dotenv
MODEL_ID=google/gemma-4-12b-it-qat-w4a16-ct
```

Use a pinned `VLLM_IMAGE` after the first successful smoke test rather than relying indefinitely on `latest`. Confirm the selected vLLM release supports the checkpoint and multimodal flags before downloading the model.

## 4. Start and inspect vLLM

```bash
docker compose pull
docker compose up -d

docker compose ps
docker compose logs -f --tail=100 vllm
```

In another terminal, wait for health:

```bash
until curl --fail --silent "http://${VLLM_BIND_ADDRESS}:8096/health" >/dev/null; do
  sleep 5
done
curl --fail --silent "http://${VLLM_BIND_ADDRESS}:8096/v1/models" | python3 -m json.tool
```

Check GPU placement and memory:

```bash
nvidia-smi
```

The container should use only GPU 1. The model download may take substantial time and disk space on first start.

## 5. Verify network exposure

From Echo:

```bash
ss -ltnp | grep ':8096'
tailscale status
```

The listener should be bound to the Tailscale address configured in `VLLM_BIND_ADDRESS`, not `0.0.0.0`. Compose also creates an Echo-only control binding on `127.0.0.1:8097` for localhost-vs-Tailscale comparisons. If host firewall policy is required, allow TCP `8096` only on the Tailscale interface and keep public/LAN ingress denied. Do not use Tailscale Funnel.

From the laptop:

```bash
cd /path/to/gemma-spike
export INFERENCE_BASE_URL=http://echo:8096/v1
uv run python scripts/smoke_test.py --image /path/to/frozen-screenshot.png
```

If `echo` is not resolvable from the laptop, use Echo's Tailscale IPv4 address instead.

## 6. Run the microbench from the laptop

```bash
uv sync
uv run python scripts/bench_inference.py \
  --image /path/to/frozen-screenshot.png \
  --runs 5 \
  --output results/gemma4-bf16.jsonl
```

Repeat for the QAT checkpoint:

```bash
export MODEL_ID=google/gemma-4-12b-it-qat-w4a16-ct
uv run python scripts/bench_inference.py \
  --image /path/to/frozen-screenshot.png \
  --runs 5 \
  --output results/gemma4-qat-w4a16.jsonl
```

Keep the endpoint on the Tailscale URL for the primary measurement. Use localhost only as an explicit network-overhead control.

## 7. Stop, restart, and recover

```bash
docker compose restart
# Stop without deleting the model cache:
docker compose down
# Remove containers and the model cache only when intentionally reclaiming disk:
docker compose down -v
```

Collect diagnostics:

```bash
docker compose ps

docker compose logs --since=30m vllm > "results/vllm-$(date -u +%Y%m%dT%H%M%SZ).log"
nvidia-smi -q > "results/nvidia-$(date -u +%Y%m%dT%H%M%SZ).txt"
```

## Troubleshooting

- **Container exits immediately:** inspect `docker compose logs vllm`; check model access, `HF_TOKEN`, vLLM/Gemma compatibility, and available VRAM.
- **GPU unavailable:** validate NVIDIA Container Toolkit and `docker run --rm --gpus '"device=1"' nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi`.
- **Laptop cannot connect:** verify Tailscale reachability, Echo's bound address, host firewall rules, and that port `8096` is not bound only to loopback.
- **Out of memory:** lower `MAX_MODEL_LEN` or `GPU_MEMORY_UTILIZATION`; do not enable tensor parallelism in this first spike.
- **Prefix-cache flag rejected:** pin a compatible vLLM image or temporarily remove `--enable-prefix-caching`, recording that the run was not prefix-cache-enabled.
