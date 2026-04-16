# Eidolum Qwen 2.5 7B — Baked Model Image for RunPod Serverless
#
# This image contains the fine-tuned Qwen model baked directly into the
# filesystem, eliminating the dependency on the US-TX-3 network volume.
# RunPod can deploy this on ANY available GPU worldwide.
#
# Build:
#   docker build --build-arg HF_TOKEN=hf_xxx -t eidolum-qwen .
#
# The model is downloaded from HuggingFace at build time (~14GB).
# Build takes ~10-15 minutes depending on network speed.

FROM vllm/vllm-openai:v0.8.5

# ── Download model from HuggingFace at build time ───────────────────────────
# The merged model must first be uploaded to a HuggingFace repo.
# See DEPLOY.md for upload instructions.
ARG HF_TOKEN
ARG HF_REPO=intensecomplexity/eidolum-qwen-merged

ENV MODEL_DIR=/models/eidolum-qwen-merged
ENV HF_HUB_ENABLE_HF_TRANSFER=1

RUN pip install --no-cache-dir huggingface_hub hf_transfer && \
    mkdir -p ${MODEL_DIR} && \
    huggingface-cli download ${HF_REPO} \
        --local-dir ${MODEL_DIR} \
        --token ${HF_TOKEN} && \
    # Clean up pip cache to keep image smaller
    rm -rf /root/.cache/pip

# ── vLLM server configuration ───────────────────────────────────────────────
# These match the existing endpoint contract in call_runpod_vllm():
#   model name:  /models/eidolum-qwen-merged
#   API format:  OpenAI-compatible chat completions
#   temperature: controlled by caller (default 0)
#   max_tokens:  controlled by caller (default 4000)
#
# gpu-memory-utilization=0.90 leaves headroom for KV cache on 24GB GPUs.
# max-model-len=8192 covers the longest YouTube transcript chunks (~6K tokens).

ENV VLLM_ARGS="--model ${MODEL_DIR} \
    --served-model-name ${MODEL_DIR} \
    --host 0.0.0.0 \
    --port 8000 \
    --gpu-memory-utilization 0.90 \
    --max-model-len 8192 \
    --dtype auto \
    --trust-remote-code"

# RunPod serverless expects the server on port 8000
EXPOSE 8000

CMD python -m vllm.entrypoints.openai.api_server ${VLLM_ARGS}
