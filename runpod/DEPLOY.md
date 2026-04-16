# Eidolum Qwen — Baked Docker Deployment

Removes the US-TX-3 datacenter lock by baking the fine-tuned model
directly into the Docker image. RunPod can deploy it on any GPU worldwide.

## Prerequisites

- Docker installed locally (or use a cloud build machine)
- HuggingFace account + API token with write access
- RunPod account with API key
- Docker Hub account (or any container registry RunPod can pull from)

---

## Step 1: Upload merged model to HuggingFace

The model weights are currently ONLY on the RunPod network volume
`eidolum-model` in US-TX-3 at `/runpod-volume/eidolum-qwen-merged`.

### Option A: From a running RunPod pod (preferred)

Spin up a temporary GPU pod in US-TX-3 with the `eidolum-model` volume
attached, then upload from there:

```bash
# On the RunPod pod:
pip install huggingface_hub

# Login to HuggingFace
huggingface-cli login  # paste your HF_TOKEN

# Create repo and upload
huggingface-cli repo create eidolum-qwen-merged --type model --private
huggingface-cli upload intensecomplexity/eidolum-qwen-merged \
    /runpod-volume/eidolum-qwen-merged . \
    --repo-type model
```

This uploads ~14GB of model files. Takes ~10-20 minutes.

### Option B: From local machine

If you've previously downloaded the model files locally:

```bash
huggingface-cli upload intensecomplexity/eidolum-qwen-merged \
    /path/to/local/eidolum-qwen-merged . \
    --repo-type model
```

---

## Step 2: Build the Docker image

```bash
cd quantanalytics/runpod

# Build with your HuggingFace token
docker build \
    --build-arg HF_TOKEN=hf_your_token_here \
    --build-arg HF_REPO=intensecomplexity/eidolum-qwen-merged \
    -t intensecomplexity/eidolum-qwen:latest .
```

The build downloads ~14GB of model weights. Total image size: ~20-25GB.

### If building on a remote machine (recommended for bandwidth)

Use a cloud VM with fast internet (e.g., AWS EC2, GCP) to avoid
uploading 20GB from a home connection.

---

## Step 3: Push to Docker Hub

```bash
docker login
docker push intensecomplexity/eidolum-qwen:latest
```

Or use any registry RunPod can pull from (GitHub Container Registry, etc.).

---

## Step 4: Create new RunPod Serverless Endpoint

Go to [RunPod Serverless](https://www.runpod.io/console/serverless) → New Endpoint.

### Settings:

| Setting | Value | Notes |
|---------|-------|-------|
| **Container Image** | `intensecomplexity/eidolum-qwen:latest` | Your Docker Hub image |
| **Network Volume** | NONE | Model is baked into the image |
| **GPU Tier** | 24GB (RTX 3090/4090/A5000) | Minimum for Qwen 7B with vLLM |
| **GPU Fallback Tiers** | 48GB (A6000/L40), 24GB PRO | For availability if 24GB is full |
| **Min Workers** | 0 | Scale to zero when idle |
| **Max Workers** | 1 | Adjust based on volume |
| **Idle Timeout** | 60 seconds | **NOT 5 seconds** — 60s prevents constant cold starts |
| **Flash Boot** | Enabled | Pre-caches the image on GPU nodes |
| **Container Disk** | 30 GB | Image is ~20-25GB, need headroom |

### Why 60s idle timeout (not 5s):

The current 5s timeout causes the GPU worker to shut down after every
single request. With the 30-minute YouTube monitor cycle, this means:
- Every cycle starts with a cold start (30-60s model load)
- You pay for 30-60s of GPU time loading the model for each cycle
- At $0.00019/s, that's $0.006-$0.012 wasted per cycle just on cold starts

With 60s timeout:
- If multiple videos arrive, subsequent ones hit the warm worker
- The monitor checks every 30min — if it finds videos, the worker
  stays warm for the next check too
- Cold start waste drops by ~80%

---

## Step 5: Update Railway environment variables

Once the new endpoint is created, note the endpoint ID from RunPod console.

```bash
railway variable set RUNPOD_ENDPOINT_ID=<new_endpoint_id> \
    --service 43fcc0e4-9f88-44bc-9278-90a6ee9284ca \
    -e production
```

**No code changes needed** — `call_runpod_vllm()` reads `RUNPOD_ENDPOINT_ID`
from env. The model name in the API payload (`/models/eidolum-qwen-merged`)
matches the `--served-model-name` in the Dockerfile.

### Update model name in code

The Docker image serves the model as `/models/eidolum-qwen-merged` (not
`/runpod-volume/...`). Update the model name via env var or code:

**Option A: Set env var on Railway** (no code change):
```bash
railway variable set RUNPOD_MODEL_NAME=/models/eidolum-qwen-merged \
    --service 43fcc0e4-9f88-44bc-9278-90a6ee9284ca \
    -e production
```

Then update `youtube_classifier.py` line ~160 and ~509 to read from env:
```python
RUNPOD_MODEL_NAME = os.getenv("RUNPOD_MODEL_NAME", "/runpod-volume/eidolum-qwen-merged")
```

**Option B: Just update the code** to use the new path directly.

---

## Step 6: Verify

```bash
# Test the new endpoint directly
curl -X POST "https://api.runpod.ai/v2/<NEW_ENDPOINT_ID>/openai/v1/chat/completions" \
    -H "Authorization: Bearer $RUNPOD_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "/models/eidolum-qwen-merged",
        "messages": [
            {"role": "system", "content": "You are a financial prediction classifier."},
            {"role": "user", "content": "I am very bullish on NVDA for 6 months."}
        ],
        "temperature": 0,
        "max_tokens": 500
    }'
```

Check Railway worker logs after deploy for:
- `[YOUTUBE-QWEN] Classified video ...` — successful classification
- `verified_by=youtube_qwen_v1` — correct tag

---

## Fallback

The old endpoint (`um17arzngz2g4b`) with US-TX-3 network volume is still
available. To revert:

```bash
railway variable set RUNPOD_ENDPOINT_ID=um17arzngz2g4b \
    --service 43fcc0e4-9f88-44bc-9278-90a6ee9284ca \
    -e production
```

---

## Cost comparison

| Setup | Cold start | Per-call cost | Monthly (est.) |
|-------|-----------|--------------|----------------|
| Volume + 5s timeout | 30-60s every cycle | $0.0012 + $0.006 cold start | ~$15-20 |
| Baked + 60s timeout | 30-60s once per burst | $0.0012 | ~$11 |
| Baked + Flash Boot | ~10s first call only | $0.0012 | ~$11 |
